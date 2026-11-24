"""Deployment routes: from a catalog template, or from any registry image (free image).

Two routers: in the public route order, `POST /plan` comes before the adoption routes
and the other deployment routes after them, and that order is kept. `deploy` (path "")
is registered by the parent router: FastAPI refuses an empty path in an included router.
"""

import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from hivora.apps.api.common import (
    ConflictOut,
    DeployOut,
    PlanOut,
    PortOut,
    app_out,
    job_ref,
    plan_out,
)
from hivora.apps.service import DeployRequest
from hivora.core.errors import HivoraError
from hivora.templates.custom import CustomEnv, CustomPort
from hivora.web.deps import Operator, RuntimeDep

plan_router = APIRouter()
router = APIRouter()


class DeployIn(BaseModel):
    template: str
    name: str = Field(max_length=100)
    inputs: dict[str, Any] = {}
    slug: str | None = Field(default=None, max_length=50)
    zone: str | None = None
    # Its ports published on the Internet or on the local network only (None: the
    # template's choice). In a zone a VPN reaches, nothing is published.
    access: Literal["public", "lan"] | None = None
    # A VPN deployed for these zones (zone dialog, "new VPN"): linked once deployed.
    vpn_zones: list[str] = Field(default=[], max_length=50)


def to_request(body: DeployIn) -> DeployRequest:
    return DeployRequest(
        template=body.template,
        name=body.name,
        inputs=body.inputs,
        slug=body.slug,
        zone=body.zone,
        access=body.access,
    )


@plan_router.post("/plan")
async def plan(body: DeployIn, _: Operator, rt: RuntimeDep) -> PlanOut:
    """Preview: generated compose, ports, conflicts. Nothing is written."""
    async with rt.sessions() as session:
        return plan_out(await rt.apps.deployer.plan_deploy(session, to_request(body)))


# Absolute safety ceiling on copies; the practical max comes from host RAM/CPU (see capacity).
MAX_COPIES = 100
# A copy with no declared memory, and the CPU a copy is assumed to want (about half a core).
DEFAULT_MEM_EACH = 256 * 2**20
CPU_PER_COPY = 0.5


def parse_bytes(text: str | None) -> int | None:
    """ "512Mi" / "1Gi" / "2G" / "1048576" -> bytes (binary Ki/Mi/Gi, decimal K/M/G)."""
    if not text:
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]i?)?\s*", text)
    if not m:
        return None
    mult = {"": 1, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12,
            "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}  # fmt: skip
    return int(float(m.group(1)) * mult[m.group(2) or ""])


class CapacityOut(BaseModel):
    max_copies: int  # how many copies the host can take (RAM and CPU), capped at MAX_COPIES
    memory_each_mb: int  # memory one copy is expected to use
    available_mb: int  # host memory free now
    cpus: int


@plan_router.get("/capacity/{template}")
async def capacity(template: str, _: Operator, rt: RuntimeDep) -> CapacityOut:
    """The most copies of this template the host can reasonably run, from free RAM, the CPU
    count and the template's declared memory. Drives the deploy menu's quantity limit."""
    import psutil

    mem = rt.catalog.get(template).template.requirements.memory
    each = (
        parse_bytes(mem.recommended if mem else None)
        or parse_bytes(mem.min if mem else None)
        or DEFAULT_MEM_EACH
    )
    vm = psutil.virtual_memory()
    cpus = psutil.cpu_count() or 1
    by_mem = int(vm.available * 0.8 // each)  # keep 20 % headroom
    by_cpu = int(cpus / CPU_PER_COPY)
    return CapacityOut(max_copies=max(1, min(by_mem, by_cpu, MAX_COPIES)),
                       memory_each_mb=each // 2**20, available_mb=int(vm.available // 2**20),
                       cpus=cpus)  # fmt: skip


class BatchPlanIn(BaseModel):
    template: str
    count: int = Field(ge=1, le=MAX_COPIES)
    inputs: dict[
        str, Any
    ] = {}  # custom form values, same for every copy (the port is auto-assigned)


class BatchPlanItemOut(BaseModel):
    name: str
    inputs: dict[str, Any]  # the exact inputs to deploy this instance (distinct web port)
    zone: str | None
    ips: list[str]
    ports: list[PortOut]
    conflicts: list[ConflictOut]


# Host ports for lab copies are taken from a high, rarely-used range (the usual 80/8080/3000
# are busy on a teaching host): we scan upward from here and skip any port already in use.
LAB_PORT_BASE = 20000
LAB_PORT_SCAN = 500


@plan_router.post("/plan/batch")
async def plan_batch(body: BatchPlanIn, _: Operator, rt: RuntimeDep) -> list[BatchPlanItemOut]:
    """Preview deploying ``count`` copies of a template: the fixed IP and host ports each one
    gets. Host ports are picked from a high range and occupied ones are skipped, so copies do
    not clash with each other or with running apps. Nothing is written (all planned in one
    session, so the IPs and ports are distinct and any remaining conflict is seen)."""
    entry = rt.catalog.get(body.template)
    port_ids = [f.id for f in entry.template.form.fields if f.type == "port"]
    out: list[BatchPlanItemOut] = []
    port = LAB_PORT_BASE
    async with rt.sessions() as session:
        for i in range(body.count):
            name = f"{entry.slug}-{i + 1}"  # plain container-style ids, numbered in order
            custom = {k: v for k, v in body.inputs.items() if k not in port_ids}
            inputs: dict[str, Any] = dict(custom)
            po = None
            # Every port field gets the next ports of the high range (consecutive, one block
            # per copy); a block that clashes is skipped as a whole.
            for _attempt in range(LAB_PORT_SCAN if port_ids else 1):
                inputs = {**custom, **{fid: port + j for j, fid in enumerate(port_ids)}}
                po = plan_out(
                    await rt.apps.deployer.plan_deploy(
                        session, DeployRequest(template=body.template, name=name, inputs=inputs)
                    )
                )
                port += len(port_ids)
                if not po.conflicts:
                    break
            assert po is not None
            out.append(
                BatchPlanItemOut(
                    name=name,
                    inputs=inputs,
                    zone=po.zone,
                    ips=po.ips,
                    ports=po.ports,
                    conflicts=po.conflicts,
                )
            )
    return out


class CustomPortIn(BaseModel):
    container: int = Field(ge=1, le=65535)
    host: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    exposure: Literal["lan", "public", "internal"] = "lan"
    web: bool = False


class CustomEnvIn(BaseModel):
    key: str = Field(max_length=128)
    value: str = Field(default="", max_length=4096)
    secret: bool = False


class CustomIn(BaseModel):
    """Any registry image: Docker Hub (nginx, grafana/grafana:12), ghcr.io/…"""

    name: str = Field(max_length=100)
    image: str = Field(max_length=300)
    zone: str | None = None
    ports: list[CustomPortIn] = Field(default=[], max_length=20)
    volumes: list[str] = Field(default=[], max_length=20)
    env: list[CustomEnvIn] = Field(default=[], max_length=100)


class ImageOut(BaseModel):
    name: str
    tag: str
    digest: str
    platforms: list[str]
    compatible: bool  # has a build for this machine
    ports: list[CustomPortIn]
    volumes: list[str]
    env: list[CustomEnvIn]


@router.get("/images/inspect")
async def inspect_image(_: Operator, rt: RuntimeDep, ref: str = Query(max_length=300)) -> ImageOut:
    """What the registry says about an image: pre-fills the free image form."""
    arch = rt.catalog.host_arch()
    info = await rt.apps.registry.inspect(ref, arch)
    return ImageOut(
        name=info.ref.name, tag=info.ref.tag, digest=info.digest, platforms=info.platforms,
        compatible=arch in info.platforms,
        ports=[CustomPortIn(container=p, host=p, protocol="udp" if proto == "udp" else "tcp")
               for p, proto in info.ports if proto in ("tcp", "udp")],
        volumes=info.volumes,
        env=[CustomEnvIn(key=k, value=v) for k, v in info.env.items()],
    )  # fmt: skip


class ImageUsedOut(BaseModel):
    image: str  # name:tag
    digest: str  # the one pinned the last time
    last_used: datetime
    apps: list[str]  # apps that still run it


@router.get("/images/history")
async def image_history(_: Operator, rt: RuntimeDep) -> list[ImageUsedOut]:
    """Free images deployed so far, newest first: the free image form offers them again."""
    return [ImageUsedOut(**h) for h in await rt.apps.custom.history()]


async def _custom(rt: RuntimeDep, body: CustomIn) -> DeployRequest:
    return await rt.apps.custom.request(
        body.name, body.image, body.zone,
        [CustomPort(p.container, p.host, p.protocol, p.exposure, p.web) for p in body.ports],
        body.volumes, [CustomEnv(e.key, e.value, e.secret) for e in body.env],
    )  # fmt: skip


@router.post("/custom/plan")
async def plan_custom(body: CustomIn, _: Operator, rt: RuntimeDep) -> PlanOut:
    """Preview the compose generated for a free image. Nothing is written."""
    req = await _custom(rt, body)
    async with rt.sessions() as session:
        return plan_out(await rt.apps.deployer.plan_deploy(session, req))


@router.post("/custom", status_code=202)
async def deploy_custom(body: CustomIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    req = await _custom(rt, body)
    app, job = await rt.apps.deployer.deploy(req)
    return DeployOut(app=app_out(rt, app, req.template), job=job_ref(job))


async def deploy(body: DeployIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    app, job = await rt.apps.deployer.deploy(to_request(body))
    if body.vpn_zones:  # queued after the deploy (one lock per app)
        await rt.vpn.set_zones(app.id, body.vpn_zones)
    return DeployOut(app=app_out(rt, app, body.template), job=job_ref(job))


class BatchItemIn(BaseModel):
    template: str
    name: str = Field(default="", max_length=100)
    inputs: dict[str, Any] = {}
    access: Literal["public", "lan"] | None = None


class BatchIn(BaseModel):
    # Several targets at once (teaching labs); the practical limit is host RAM/CPU (see capacity).
    items: list[BatchItemIn] = Field(min_length=1, max_length=MAX_COPIES)


class BatchResultOut(BaseModel):
    template: str
    ok: bool
    app: DeployOut | None = None  # the deployed app and its job, when it started
    error: str | None = None  # the failure code, when it did not (e.g. labs_disabled)


@router.post("/batch", status_code=202)
async def deploy_batch(body: BatchIn, _: Operator, rt: RuntimeDep) -> list[BatchResultOut]:
    """Deploy each target on its own (one lock/job per app): a failure is reported for that
    item and never stops the others, so a whole class of labs goes up in one click."""
    results: list[BatchResultOut] = []
    for item in body.items:
        req = DeployRequest(template=item.template, name=item.name, inputs=item.inputs,
                            access=item.access)  # fmt: skip
        try:
            app, job = await rt.apps.deployer.deploy(req)
            results.append(BatchResultOut(
                template=item.template, ok=True,
                app=DeployOut(app=app_out(rt, app, item.template), job=job_ref(job)),
            ))  # fmt: skip
        except HivoraError as exc:
            results.append(BatchResultOut(template=item.template, ok=False, error=exc.code))
    return results
