"""Hand-written compose routes (admin)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.apps.api.common import ConflictOut, DeployOut, JobRef, app_out, job_ref
from hivora.apps.ports import PortConflict
from hivora.web.deps import Admin, RuntimeDep

router = APIRouter()


class ComposeIn(BaseModel):
    compose_yaml: str = Field(min_length=1, max_length=200_000)


class NewComposeIn(ComposeIn):
    name: str = Field(min_length=1, max_length=100)
    zone: str | None = None  # zone slug; None: unclassified (ignored for a lab)
    labs: bool = False  # a target of the Cybersecurity module: in the Labo zone


class NewComposePlanOut(BaseModel):
    slug: str
    compose_yaml: str  # as Hivora will write it
    problems: list[str]
    conflicts: list[ConflictOut]


def _conflicts(found: list[PortConflict]) -> list[ConflictOut]:
    return [ConflictOut(port=c.port, protocol=c.protocol, used_by=c.used_by,
                        suggestion=c.suggestion) for c in found]  # fmt: skip


@router.post("/compose/plan")
async def plan_new_compose(body: NewComposeIn, _: Admin, rt: RuntimeDep) -> NewComposePlanOut:
    """Preview a new app from your own compose file (admin: it runs as written). Nothing is
    written."""
    async with rt.sessions() as session:
        p = await rt.apps.compose.plan_new(session, body.name, body.zone, body.compose_yaml,
                                           labs=body.labs)  # fmt: skip
    return NewComposePlanOut(slug=p.slug, compose_yaml=p.compose_yaml, problems=p.problems,
                             conflicts=_conflicts(p.conflicts))  # fmt: skip


@router.post("/compose", status_code=202)
async def deploy_new_compose(body: NewComposeIn, _: Admin, rt: RuntimeDep) -> DeployOut:
    """Deploy your own compose file as a new app."""
    app, job = await rt.apps.compose.create(body.name, body.zone, body.compose_yaml,
                                            labs=body.labs)  # fmt: skip
    return DeployOut(app=app_out(rt, app, None), job=job_ref(job))


class ComposePlanOut(BaseModel):
    diff: str
    problems: list[str]  # why it cannot be applied (empty: it can)
    conflicts: list[ConflictOut]


@router.post("/{app_id}/compose/plan")
async def plan_compose(app_id: int, body: ComposeIn, _: Admin, rt: RuntimeDep) -> ComposePlanOut:
    """Check a hand-written compose file (resolved by Compose, then security checks)."""
    async with rt.sessions() as session:
        p = await rt.apps.compose.plan(session, app_id, body.compose_yaml)
    return ComposePlanOut(diff=p.diff, problems=p.problems, conflicts=_conflicts(p.conflicts))


@router.put("/{app_id}/compose", status_code=202)
async def apply_compose(app_id: int, body: ComposeIn, _: Admin, rt: RuntimeDep) -> JobRef:
    """Apply a hand-written compose file as a new revision (admin: it runs as written)."""
    return job_ref(await rt.apps.compose.apply(app_id, body.compose_yaml))
