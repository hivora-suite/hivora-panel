"""Labs VPN (/api/v1/labs/vpn): one WireGuard for all labs, a class roster, labs per student.

A student is a VPN client. The teacher creates the roster first (no lab: the student reaches
nothing), then assigns labs. The server enforces it: the client's access rights hold the labs'
fixed IPs (``access.hosts``), everything else — other labs, the LAN, the Internet, the other
students — is dropped, whatever the student edits in their ``.conf``. The ``.conf`` routes the
whole Labo zone, so it stays valid when the student is moved to another lab. Which labs a
student has is read back from those IPs: nothing extra is stored.
"""

import asyncio
import io
import re
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from hivora.addressing.models import IpAssignment
from hivora.addressing.service import LABS_VPN_SUBNET, LABS_ZONE_SUBNET
from hivora.apps.models import Application
from hivora.apps.service import DeployRequest
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.db.models import Setting
from hivora.jobs.models import JobStatus
from hivora.web.deps import Admin, Operator, RuntimeDep, Viewer
from hivora.zones import LABS_ZONE, zone_network
from hivora.zones.service import find_zone

router = APIRouter(tags=["labs"])

STATE = "labs.vpn"  # Setting row remembering the VPN app id
VPN_NAME = "labs-vpn"
VPN_PORT = 51821  # the admin VPN keeps 51820


class LabsVpnDisabledError(ConflictError):
    code = "labs_vpn_disabled"


async def _vpn_app_id(rt: Any) -> int | None:
    """The single labs WireGuard app, remembered or found in the labs zone (None: not enabled)."""
    async with rt.sessions() as s:
        row = await s.get(Setting, STATE)
        if row and isinstance(row.value, dict) and (aid := row.value.get("app_id")):
            if await s.get(Application, int(aid)):
                return int(aid)
        zone = await find_zone(s, LABS_ZONE)
        if zone is None:
            return None
        app = await s.scalar(
            select(Application).where(Application.zone_id == zone.id, Application.name == VPN_NAME)
        )
        return app.id if app else None


async def _labs(rt: Any) -> tuple[list[dict[str, Any]], str]:
    """The deployed labs ({slug, name, app_id, ip}, by name) and the Labo zone's subnet."""
    async with rt.sessions() as s:
        zone = await find_zone(s, LABS_ZONE)
        if zone is None:
            return [], LABS_ZONE_SUBNET
        rows = (
            await s.execute(
                select(IpAssignment.address, Application.slug, Application.name, Application.id)
                .join(Application, Application.slug == IpAssignment.app)
                .where(IpAssignment.network == zone_network(zone), Application.name != VPN_NAME)
                .order_by(Application.name)
            )
        ).all()
        subnet = getattr(zone, "subnet", None) or LABS_ZONE_SUBNET
    seen: dict[str, dict[str, Any]] = {}
    for addr, slug, name, app_id in rows:  # one IP per lab (its first container)
        seen.setdefault(slug, {"slug": slug, "name": name, "app_id": app_id, "ip": addr})
    return list(seen.values()), subnet


def _endpoint_host(rt: Any) -> str | None:
    s = rt.settings
    host: str | None = s.admin_vpn_host or s.host_public_ip or s.host_lan_ip
    return host


def _access(ips: list[str]) -> dict[str, Any]:
    """Server-side rights of a student: only these lab IPs, nothing else."""
    return {"internet": False, "lan": False, "zones": [], "hosts": ips}


class LabsVpnStudentOut(BaseModel):
    id: int
    name: str
    labs: list[str]  # slugs of the labs this student may reach
    enabled: bool
    online: bool
    address: str


class LabsVpnLabOut(BaseModel):
    slug: str
    name: str
    app_id: int
    ip: str
    students: int
    online: int


class LabsVpnStatusOut(BaseModel):
    enabled: bool
    running: bool
    host: str | None
    subnet: str | None
    labs: list[LabsVpnLabOut]
    students: list[LabsVpnStudentOut]


def _student_labs(client: dict[str, Any], by_ip: dict[str, str]) -> list[str]:
    hosts = (client.get("access") or {}).get("hosts") or []
    return [by_ip[h] for h in hosts if h in by_ip]


async def _state(rt: Any, app_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """(labs, clients with their "labs" slugs, zone subnet)."""
    labs, subnet = await _labs(rt)
    by_ip = {lab["ip"]: lab["slug"] for lab in labs}
    clients = (await rt.vpn.overview(app_id))["clients"]
    for c in clients:
        c["labs"] = _student_labs(c, by_ip)
    return labs, clients, subnet


async def _require_vpn(rt: Any) -> int:
    app_id = await _vpn_app_id(rt)
    if app_id is None:
        raise LabsVpnDisabledError("enable the labs VPN first")
    return app_id


@router.get("/vpn")
async def status(_: Viewer, rt: RuntimeDep) -> LabsVpnStatusOut:
    app_id = await _vpn_app_id(rt)
    if app_id is None:
        labs, _sub = await _labs(rt)
        return LabsVpnStatusOut(enabled=False, running=False, host=_endpoint_host(rt), subnet=None,
                                labs=[LabsVpnLabOut(**lab, students=0, online=0) for lab in labs],
                                students=[])  # fmt: skip
    over = await rt.vpn.overview(app_id)
    labs, clients, _sub = await _state(rt, app_id)
    return LabsVpnStatusOut(
        enabled=True, running=over["running"], host=_endpoint_host(rt), subnet=over["subnet"],
        labs=[LabsVpnLabOut(**lab, students=sum(lab["slug"] in c["labs"] for c in clients),
                            online=sum(lab["slug"] in c["labs"] and c["online"] for c in clients))
              for lab in labs],
        students=[LabsVpnStudentOut(id=c["id"], name=c["name"], labs=c["labs"],
                                    enabled=c["enabled"], online=c.get("online", False),
                                    address=c["address"])
                  for c in clients])  # fmt: skip


@router.post("/vpn/enable", status_code=202)
async def enable(_: Admin, rt: RuntimeDep) -> dict[str, int]:
    """Deploy the one WireGuard that reaches the labs zone (so labs stop publishing on the host
    and each is reachable at its own IP). Idempotent."""
    if (existing := await _vpn_app_id(rt)) is not None:
        return {"app_id": existing}
    host = _endpoint_host(rt)
    if not host:
        raise ConflictError("no address to reach the VPN (set the server's public/LAN IP)")
    inputs = {
        "host": host,
        "vpn_port": VPN_PORT,
        "vpn_subnet": LABS_VPN_SUBNET,
        "vpn_zones": LABS_ZONE,
    }
    app, job = await rt.apps.deployer.deploy(
        DeployRequest(template="wireguard", name=VPN_NAME, inputs=inputs, zone=LABS_ZONE)
    )
    async with rt.sessions() as s:
        await s.merge(Setting(key=STATE, value={"app_id": app.id}))
        await s.commit()
        labs = list(
            await s.scalars(
                select(Application.id).where(
                    Application.zone_id == app.zone_id, Application.id != app.id
                )
            )
        )
    await rt.apps.revisions.redeploy(labs)  # labs already up stop publishing on the host
    return {"app_id": app.id, "job_id": job.id}


async def _wait_job(rt: Any, job_id: int, timeout_s: float = 120.0) -> None:
    """Block until a job finishes (the request stays open so the UI shows one clear outcome)."""
    done = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if (await rt.jobs.get(job_id)).status in done:
            return
        await asyncio.sleep(0.3)


@router.post("/vpn/disable", status_code=202)
async def disable(_: Admin, rt: RuntimeDep) -> dict[str, int]:
    """Remove the labs VPN (students' configs die with it). The labs publish their ports on the
    host again. Refused while a target that must be scanned (``needs_vpn``) is deployed.

    One job on the VPN app (its removal), awaited so the labs are re-planned only once it is
    gone (``vpn_zones`` then empty → no more ``vpn_only``). No revision update beforehand: two
    jobs on the same app would race (a removed app leaves the other job without an app)."""
    app_id = await _require_vpn(rt)
    async with rt.sessions() as s:
        zone = await find_zone(s, LABS_ZONE)
        apps = (
            []
            if zone is None
            else list(
                await s.scalars(
                    select(Application).where(
                        Application.zone_id == zone.id, Application.id != app_id
                    )
                )
            )
        )
        scanned = []
        for app in apps:
            lab = (await rt.apps.planner.entry_of(s, app)).template.metadata.lab
            if lab and lab.needs_vpn:
                scanned.append(app.name)
    if scanned:
        raise ConflictError("these targets need the labs VPN: remove them first",
                            apps=", ".join(scanned))  # fmt: skip
    async with rt.sessions() as s:  # forget the VPN now: a second click sees it gone (409)
        if row := await s.get(Setting, STATE):
            await s.delete(row)
            await s.commit()
    job = await rt.apps.lifecycle.remove(app_id, remove_data=True)
    await _wait_job(rt, job.id)
    await rt.apps.revisions.redeploy([a.id for a in apps])  # now republished on the host
    return {"labs": len(apps)}


NAME = r"^[A-Za-z0-9 _.-]{1,60}$"


class StudentsIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=200)  # the class roster, one per student


@router.post("/vpn/students", status_code=201)
async def create_students(body: StudentsIn, _: Operator, rt: RuntimeDep) -> list[int]:
    """Add students to the roster, with no lab yet (they reach nothing until assigned)."""
    app_id = await _require_vpn(rt)
    names = list(dict.fromkeys(n.strip() for n in body.names if n.strip()))
    if not names or not all(re.fullmatch(NAME, n) for n in names):
        raise ValidationError("names: letters, digits, space, _ . - only (60 max)", field="names")
    _l, subnet = await _labs(rt)
    return [await rt.vpn.create(app_id, n, allowed_ips=[subnet], access=_access([])) for n in names]


class StudentLabsIn(BaseModel):
    labs: list[str] = Field(default=[], max_length=50)  # lab slugs; empty: reaches nothing


@router.put("/vpn/students/{cid}/labs", status_code=204)
async def set_student_labs(cid: int, body: StudentLabsIn, _: Operator, rt: RuntimeDep) -> None:
    app_id = await _require_vpn(rt)
    labs, _sub = await _labs(rt)
    ip = {lab["slug"]: lab["ip"] for lab in labs}
    if missing := [s for s in body.labs if s not in ip]:
        raise NotFoundError("no such lab, or it is not deployed", slug=missing[0])
    await rt.vpn.update(app_id, cid, access=_access([ip[s] for s in dict.fromkeys(body.labs)]))


def balance(students: list[list[str]], labs: list[str]) -> list[str | None]:
    """For each student, the lab to add (None: already has one): the least-filled lab first,
    ties by lab order. Pure, so it is tested without a VPN."""
    load = {lab: sum(lab in s for s in students) for lab in labs}
    out: list[str | None] = []
    for s in students:
        if s or not labs:
            out.append(None)
            continue
        pick = min(labs, key=lambda lab: load[lab])
        load[pick] += 1
        out.append(pick)
    return out


@router.post("/vpn/distribute")
async def distribute(_: Operator, rt: RuntimeDep) -> dict[str, int]:
    """Give every student without a lab one, spreading them evenly over the deployed labs."""
    app_id = await _require_vpn(rt)
    labs, clients, _sub = await _state(rt, app_id)
    ip = {lab["slug"]: lab["ip"] for lab in labs}
    picks = balance([c["labs"] for c in clients], [lab["slug"] for lab in labs])
    done = 0
    for c, pick in zip(clients, picks, strict=True):
        if pick:
            await rt.vpn.update(app_id, c["id"], access=_access([ip[pick]]))
            done += 1
    return {"assigned": done}


@router.post("/vpn/unassign")
async def unassign(_: Operator, rt: RuntimeDep) -> dict[str, int]:
    """Take every student off every lab (students and their configs stay; they reach nothing)."""
    app_id = await _require_vpn(rt)
    _l, clients, _sub = await _state(rt, app_id)
    done = 0
    for c in clients:
        if c["labs"]:
            await rt.vpn.update(app_id, c["id"], access=_access([]))
            done += 1
    return {"removed": done}


# What the students read in the class export, per panel language. Only the IPs: finding the
# ports is the recon phase of the exercise.
README = {
    "fr": (
        "Accès aux labos de cybersécurité\n"
        "================================\n\n"
        "Chaque élève a son dossier : ouvrez le vôtre.\n\n"
        "1. Installez WireGuard (https://www.wireguard.com/install/).\n"
        "2. Importez votre fichier .conf (« Importer un tunnel depuis un fichier »).\n"
        "3. Activez le tunnel.\n"
        "4. Votre .txt donne l'IP de vos cibles : c'est tout ce que vous pouvez joindre.\n\n"
        "N'utilisez que votre propre config : une config utilisée par deux personnes à la fois\n"
        "coupe la connexion des deux.\n"
    ),
    "en": (
        "Cybersecurity labs access\n"
        "=========================\n\n"
        "Each student has a folder: open yours.\n\n"
        "1. Install WireGuard (https://www.wireguard.com/install/).\n"
        '2. Import your .conf file ("Import tunnel(s) from file").\n'
        "3. Turn the tunnel on.\n"
        "4. Your .txt gives your targets' IPs: they are all you can reach.\n\n"
        "Only use your own config: a config used by two people at once\n"
        "drops both connections.\n"
    ),
}
STUDENT = {
    "fr": ("Élève : {name}\n\nCibles :\n{targets}\n\n"
           "Connexion : importez {name}.conf dans WireGuard, activez le tunnel,\n"
           "puis travaillez sur l'IP ci-dessus (ex. : nmap {first}).\n"
           "Les autres IP ne répondront pas : c'est normal.\n",
           "  (aucun lab attribué pour l'instant : demandez à votre enseignant)"),
    "en": ("Student: {name}\n\nTargets:\n{targets}\n\n"
           "Connection: import {name}.conf into WireGuard, turn the tunnel on,\n"
           "then work on the IP above (e.g. nmap {first}).\n"
           "Other IPs will not answer: that is expected.\n",
           "  (no lab assigned yet: ask your teacher)"),
}  # fmt: skip


def student_sheet(name: str, targets: list[tuple[str, str]], lang: str) -> str:
    """The .txt a student reads: their labs and IPs, and how to connect."""
    text, none = STUDENT[lang]
    lines = "\n".join(f"  - {lab} : {ip}" for lab, ip in targets) or none
    first = targets[0][1] if targets else "<IP>"
    return text.format(name=name, targets=lines, first=first)


@router.get("/vpn/configs.zip")
async def configs_zip(_: Operator, rt: RuntimeDep, lab: str | None = None,
                      lang: Literal["fr", "en"] = "fr") -> Response:  # fmt: skip
    """The class export: a README, then one folder per student (only those on ``lab`` if
    given) with their WireGuard .conf and a .txt naming their targets' IPs."""
    app_id = await _require_vpn(rt)
    labs, clients, _sub = await _state(rt, app_id)
    by_slug = {x["slug"]: x for x in labs}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("TUTO-SETUP.txt" if lang == "fr" else "SETUP-GUIDE.txt", README[lang])
        for c in clients:
            if lab is not None and lab not in c["labs"]:
                continue
            name = c["name"]
            targets = [(by_slug[s]["name"], by_slug[s]["ip"]) for s in c["labs"]]
            z.writestr(f"{name}/{name}.conf", await rt.vpn.configuration(app_id, c["id"]))
            z.writestr(f"{name}/{name}.txt", student_sheet(name, targets, lang))
    filename = f"labs-vpn-{lab or ('classe' if lang == 'fr' else 'class')}.zip"
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vpn/students/{cid}/config")
async def student_config(cid: int, _: Operator, rt: RuntimeDep) -> Response:
    conf = await rt.vpn.configuration(await _require_vpn(rt), cid)
    return Response(conf, media_type="text/plain")


@router.get("/vpn/students/{cid}/qr")
async def student_qr(cid: int, _: Operator, rt: RuntimeDep) -> Response:
    return Response(await rt.vpn.qrcode(await _require_vpn(rt), cid), media_type="image/svg+xml")


@router.delete("/vpn/students/{cid}", status_code=204)
async def delete_student(cid: int, _: Operator, rt: RuntimeDep) -> None:
    await rt.vpn.delete(await _require_vpn(rt), cid)
