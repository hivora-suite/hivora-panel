"""Hand-written compose files (admin): resolved by Compose, checked, applied as a revision."""

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.compose_check import problems as compose_problems
from hivora.apps.core import (
    LabsDisabledError,
    PortConflictError,
    conflict_dict,
    decrypt_secrets,
    free_slug,
    get_app,
    latest_revision,
    queue_revision,
    slugify,
)
from hivora.apps.models import (
    Application,
    AppRevision,
    DesiredState,
    Exposure,
    Origin,
    PortBinding,
    RevisionStatus,
    Service,
    ServiceRole,
    VolumeKind,
    VolumeMount,
)
from hivora.apps.ports import PortConflict, find_conflicts, used_ports
from hivora.compose_runner import ComposeError, ComposeRunner
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, ValidationError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.jobs import Job, JobKind, JobQueue
from hivora.state import StateStore
from hivora.templates.compiler import PortPlan
from hivora.templates.expressions import secret_env_name
from hivora.zones import LABS_ZONE, Zone, ensure_labs_zone, get_zone, zone_network

if TYPE_CHECKING:
    from hivora.addressing import Addressing


class ComposeRejectedError(ValidationError):
    code = "compose_rejected"


@dataclass(frozen=True, slots=True)
class ComposePlan:
    app: Application
    compose_yaml: str
    diff: str
    problems: list[str]  # what forbids applying it (empty: fine)
    conflicts: list[PortConflict]
    services: list[Service]  # declared services, read from the resolved model


@dataclass(frozen=True, slots=True)
class NewComposePlan:
    """A new app from the user's own compose file, as Hivora will write it."""

    slug: str
    name: str
    zone: Zone | None
    compose_yaml: str  # with the project name, Hivora's labels and the fixed networks added
    problems: list[str]
    conflicts: list[PortConflict]
    services: list[Service]


class ComposeEdit:
    def __init__(
        self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession],
        runner: ComposeRunner, state: StateStore, jobs: JobQueue, box: SecretBox,
        bus: EventBus, clock: Clock,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.runner = runner
        self.state = state
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock
        self.addressing: Addressing | None = None  # set by the runtime (None: Docker chooses)

    async def _check(
        self, session: AsyncSession, slug: str, compose_yaml: str, env: dict[str, str]
    ) -> tuple[list[str], list[PortConflict], list[Service]]:
        """Resolved by Compose, then the safety checks and the host ports in use."""
        try:
            model = await self.runner.check(slug, compose_yaml, env)
        except ComposeError as exc:
            return [f"compose: {exc}"[:500]], [], []
        roots = [self.settings.volumes_root / slug, self.runner.project_dir(slug),
                 self.runner.apps_dir / f".check-{slug}"]  # fmt: skip
        found = compose_problems(model, slug, roots)
        services = [] if found else _services_from_model(model)
        used = await used_ports(session, self.state, exclude_app=slug)
        conflicts = find_conflicts((
            PortPlan(sv.name, p.container_port, p.host_port, p.protocol, "other",
                     p.exposure.value, p.host_ip)
            for sv in services for p in sv.ports
        ), used)  # fmt: skip
        return found, conflicts, services

    async def plan(self, session: AsyncSession, app_id: int, compose_yaml: str) -> ComposePlan:
        """Validate a hand-written compose file: resolved by Compose, then checked."""
        app = await get_app(session, app_id)
        secrets = await decrypt_secrets(session, self.box, app.id)
        env = {secret_env_name(k): v for k, v in secrets.items()}
        found, conflicts, services = await self._check(session, app.slug, compose_yaml, env)
        if found and found[0].startswith("compose: "):
            return ComposePlan(app, compose_yaml, "", found, [], [])
        latest = await latest_revision(session, app.id)
        diff = "".join(difflib.unified_diff(
            (latest.compose_yaml if latest else "").splitlines(keepends=True),
            compose_yaml.splitlines(keepends=True),
            fromfile="current", tofile="edited",
        ))  # fmt: skip
        return ComposePlan(app, compose_yaml, diff, found, conflicts, services)

    async def plan_new(self, session: AsyncSession, name: str, zone_slug: str | None,
                       compose_yaml: str, *, labs: bool = False) -> NewComposePlan:  # fmt: skip
        """A new app from the user's own compose file. Hivora adds the project name, its
        labels and the networks (fixed addresses of the plan); the file keeps the rest.
        Called in the caller's session: a preview that is not committed writes nothing."""
        if labs:
            if not self.settings.labs:
                raise LabsDisabledError("the security labs are turned off on this panel")
            zone: Zone | None = await ensure_labs_zone(session, self.clock)
        else:
            zone = await get_zone(session, zone_slug) if zone_slug else None
            if zone and zone.slug == LABS_ZONE:
                raise ConflictError("the Labo zone only holds security labs", slug=zone.slug)
        name = name.strip()
        slug = await free_slug(session, slugify(name))
        try:
            model = yaml.safe_load(compose_yaml)
        except yaml.YAMLError as exc:
            return NewComposePlan(slug, name, zone, compose_yaml, [f"yaml: {exc}"[:500]], [], [])
        services = model.get("services") if isinstance(model, dict) else None
        if not isinstance(model, dict) or not isinstance(services, dict) or not services:
            return NewComposePlan(slug, name, zone, compose_yaml, ["no service"], [], [])
        # Hivora places every container (zone, fixed address): no network of the file's own.
        own_nets = [f"service {n}: networks are set by Hivora, remove them" for n, s in
                    services.items() if isinstance(s, dict) and s.get("networks")]  # fmt: skip
        if model.get("networks") or own_nets:
            problems = own_nets or ["networks are set by Hivora, remove them"]
            return NewComposePlan(slug, name, zone, compose_yaml, problems, [], [])
        text = await self._with_hivora(session, model, slug, zone)
        found, conflicts, declared = await self._check(session, slug, text, {})
        return NewComposePlan(slug, name, zone, text, found, conflicts, declared)

    async def _with_hivora(self, session: AsyncSession, model: dict[str, Any], slug: str,
                           zone: Zone | None) -> str:  # fmt: skip
        """The file with what Hivora relies on: project name, labels, fixed networks."""
        services: dict[str, Any] = model["services"]
        fixed = (await self.addressing.for_app(session, slug, zone, list(services), [])
                 if self.addressing else None)  # fmt: skip
        own = zone_network(zone)
        for name, svc in services.items():
            svc = services[name] = svc if isinstance(svc, dict) else {}
            labels = svc.get("labels") or {}
            if isinstance(labels, list):
                labels = dict(str(x).partition("=")[::2] for x in labels)
            svc["labels"] = {**labels, "io.hivora.app": slug, "io.hivora.revision": "1",
                             **({"io.hivora.zone": zone.slug} if zone else {})}  # fmt: skip
            nets: dict[str, dict[str, str]] = {"default": {}, **({own: {}} if own else {})}
            for net, service, ip in fixed.addresses if fixed else ():
                if service == name:
                    nets.setdefault(net, {})["ipv4_address"] = ip
            svc["networks"] = nets
        networks: dict[str, Any] = {}
        if fixed and fixed.default_subnet:
            networks["default"] = {"ipam": {"config": [{"subnet": fixed.default_subnet}]}}
        if own:
            networks[own] = {"name": own, "external": True}
        body = {"name": slug, **{k: v for k, v in model.items() if k != "name"}}
        if networks:
            body["networks"] = networks
        head = f"# Your compose file, deployed by Hivora as app {slug}.\n"
        return head + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)

    async def create(self, name: str, zone_slug: str | None, compose_yaml: str, *,
                     labs: bool = False) -> tuple[Application, Job]:  # fmt: skip
        """Deploy the user's own compose file as a new app (revision 1, written as checked)."""
        async with self.sessions() as session, session.begin():
            plan = await self.plan_new(session, name, zone_slug, compose_yaml, labs=labs)
            if plan.problems:
                raise ComposeRejectedError("this compose file cannot be applied",
                                           problems=plan.problems)  # fmt: skip
            if plan.conflicts:
                conflicts = [conflict_dict(c) for c in plan.conflicts]
                raise PortConflictError("host ports already in use", conflicts=conflicts)
            now = self.clock.now()
            app = Application(
                slug=plan.slug, name=plan.name, zone_id=plan.zone.id if plan.zone else None,
                origin=Origin.COMPOSE, template_version_id=None,
                desired_state=DesiredState.RUNNING, icon=None, notes="", created_at=now,
                services=plan.services,
            )  # fmt: skip
            session.add(app)
            await session.flush()
            revision = AppRevision(app_id=app.id, number=1, inputs={},
                                   compose_yaml=plan.compose_yaml, created_at=now,
                                   status=RevisionStatus.PENDING, custom_compose=True)  # fmt: skip
            session.add(revision)
            await session.flush()
            job = self.jobs.add(session, JobKind.DEPLOY, app_id=app.id, app_slug=app.slug,
                                params={"revision_id": revision.id})  # fmt: skip
        self.jobs.wake()
        self.bus.publish("app.created", app=app.slug, template=None, job=job.id)
        return app, job

    async def apply(self, app_id: int, compose_yaml: str, *,
                    event: str = "app.compose_edited") -> Job:  # fmt: skip
        async with self.sessions() as session, session.begin():
            plan = await self.plan(session, app_id, compose_yaml)
            if plan.problems:
                raise ComposeRejectedError("this compose file cannot be applied",
                                           problems=plan.problems)  # fmt: skip
            if plan.conflicts:
                conflicts = [conflict_dict(c) for c in plan.conflicts]
                raise PortConflictError("host ports already in use", conflicts=conflicts)
            app = plan.app
            latest = await latest_revision(session, app.id)
            revision = AppRevision(
                app_id=app.id, number=(latest.number if latest else 0) + 1,
                inputs=dict(latest.inputs) if latest else {}, compose_yaml=compose_yaml,
                diff_from_previous=plan.diff, created_at=self.clock.now(),
                status=RevisionStatus.PENDING, custom_compose=True,
                template_version_id=latest.template_version_id if latest else None,
                overrides=latest.overrides if latest else None,
            )  # fmt: skip
            job = await queue_revision(session, self.jobs, app, revision, plan.services)
        self.jobs.wake()
        self.bus.publish(event, app=app.slug, revision=revision.number, job=job.id)
        return job


def _services_from_model(model: dict[str, Any]) -> list[Service]:
    """Services, ports and bind mounts of a resolved compose model (hand-written file)."""
    out: list[Service] = []
    for name, svc in (model.get("services") or {}).items():
        ports = []
        for p in svc.get("ports") or []:
            if not isinstance(p, dict) or not p.get("published"):
                continue
            ports.append(PortBinding(
                host_ip=p.get("host_ip") or None, host_port=int(str(p["published"]).split("-")[0]),
                container_port=int(p.get("target", 0)), protocol=p.get("protocol", "tcp"),
                purpose="other", exposure=Exposure.PUBLIC if not p.get("host_ip") else Exposure.LAN,
            ))  # fmt: skip
        volumes = [
            VolumeMount(kind=VolumeKind.BIND, source=str(v["source"]), target=str(v["target"]),
                        read_only=bool(v.get("read_only")), backup=True)
            for v in svc.get("volumes") or []
            if isinstance(v, dict) and v.get("type") == "bind" and v.get("source")
        ]  # fmt: skip
        out.append(Service(
            name=name, image=str(svc.get("image") or ""), role=ServiceRole.MAIN if not out
            else ServiceRole.SIDECAR, restart_policy=str(svc.get("restart") or "no"),
            ports=ports, volumes=volumes,
        ))  # fmt: skip
    return out
