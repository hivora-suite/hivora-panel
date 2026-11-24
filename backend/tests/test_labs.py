"""Security-lab module — Lot 1: the ``security-lab`` category, its ``lab`` block, and the
``labs`` setting that gates the catalog and new deploys (mirrors the games toggle)."""

import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from conftest import FAKE, REPO_TEMPLATES
from fastapi.testclient import TestClient
from helpers import API, admin, code, wait_job
from test_templates import minimal

from hivora import __version__
from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.labs.api import balance
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.templates import TemplateInvalidError
from hivora.templates.catalog import parse_template
from hivora.vpn import wireguard as wg
from hivora.vpn.acl import access_of


def lab_doc(**lab: Any) -> dict[str, Any]:
    block = {"phase": "exploitation", "cves": ["CVE-2021-44228"], "os": ["linux"],
             "tech": ["web"], "difficulty": "easy",
             "summary": "A vulnerable target.", "solution": "Exploit then patch."}  # fmt: skip
    block.update(lab)
    return minimal(metadata={"slug": "lab-demo", "name": "Lab", "version": "1.0.0",
                             "category": "security-lab", "lab": block})  # fmt: skip


def test_security_lab_template_parses_with_its_lab_block() -> None:
    t = parse_template(yaml.safe_dump(lab_doc()), require_pinned=False)
    assert t.metadata.category == "security-lab"
    assert t.metadata.lab is not None
    assert t.metadata.lab.phase == "exploitation"
    assert t.metadata.lab.cves == ["CVE-2021-44228"]


def test_security_lab_needs_a_lab_block() -> None:
    doc = lab_doc()
    del doc["metadata"]["lab"]
    with pytest.raises(TemplateInvalidError):
        parse_template(yaml.safe_dump(doc), require_pinned=False)


def test_normal_template_may_not_carry_a_lab_block() -> None:
    doc = minimal()
    doc["metadata"]["lab"] = {"phase": "recon"}
    with pytest.raises(TemplateInvalidError):
        parse_template(yaml.safe_dump(doc), require_pinned=False)


def test_malformed_cve_is_rejected() -> None:
    with pytest.raises(TemplateInvalidError):
        parse_template(yaml.safe_dump(lab_doc(cves=["not-a-cve"])), require_pinned=False)


# --- Integration (Lot 1bis + 2): the labs toggle, the Labo zone, topology exclusion -------


def _runtime(tmp_path: Path, *, labs: bool) -> Runtime:
    settings = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                        catalog_dir=REPO_TEMPLATES, dev_insecure_cookies=True,
                        puid=os.getuid(), pgid=os.getgid(), host_lan_ip="192.168.1.10",
                        labs=labs)  # fmt: skip
    return Runtime.build(settings, gateway=FakeDockerGateway(), compose_cmd=FAKE,
                         compose_env={"FAKE_COMPOSE_MODE": "leak"})  # fmt: skip


def test_labs_off_hides_targets_and_refuses_deploy(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=False))) as client:
        admin(client)
        listed = client.get(f"{API}/templates").json()
        assert listed and all(t["category"] != "security-lab" for t in listed)
        refused = client.post(f"{API}/apps", json={"template": "juice-shop", "name": "js",
                                                   "inputs": {"web_port": 3000}})  # fmt: skip
        assert refused.status_code == 403 and code(refused) == "labs_disabled"
        # The System page shows the module off, with this version's installer to turn it on.
        info = client.get(f"{API}/system/info").json()
        assert info["labs"] is False and info["games"] is True
        assert info["installer"] == (
            'sudo sh -c "$(curl -fsSL https://github.com/hivora-suite/hivora-panel/releases/'
            f'download/v{__version__}/install.sh)" install.sh'
        )


def test_labs_on_deploys_into_its_own_zone_and_stays_out_of_topology(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        listed = {t["slug"]: t for t in client.get(f"{API}/templates").json()}
        assert listed["juice-shop"]["lab"]["phase"] == "actions"
        assert listed["webgoat"]["category"] == "security-lab"
        # The list leaves the long solutions out; one lab's detail carries it.
        assert "solution" not in listed["juice-shop"]["lab"]
        assert client.get(f"{API}/templates/juice-shop").json()["lab"]["solution"]

        out = client.post(f"{API}/apps", json={"template": "juice-shop", "name": "js",
                                               "inputs": {"web_port": 3000}}).json()  # fmt: skip
        assert wait_job(client, out["job"]["id"])["status"] == "succeeded"
        app_id = out["app"]["id"]

        zones = {z["slug"]: z for z in client.get(f"{API}/zones").json()}
        assert "security-labs" in zones
        app = next(a for a in client.get(f"{API}/apps").json() if a["id"] == app_id)
        assert app["zone_id"] == zones["security-labs"]["id"]

        graph = client.get(f"{API}/topology").json()
        assert all(n["key"] != f"app:{app_id}" for n in graph["nodes"])
        assert all(n.get("slug") != "security-labs" for n in graph["nodes"])


def test_own_compose_target_lands_in_the_labo_zone(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        body = {
            "name": "Ma cible",
            "labs": True,
            "zone": "ignored",
            "compose_yaml": "services:\n  vuln:\n    image: vulnerables/web-dvwa\n",
        }
        out = client.post(f"{API}/apps/compose", json=body).json()
        assert wait_job(client, out["job"]["id"])["status"] == "succeeded"
        zones = {z["slug"]: z["id"] for z in client.get(f"{API}/zones").json()}
        assert out["app"]["zone_id"] == zones["security-labs"]
        text = client.get(f"{API}/apps/{out['app']['id']}/compose").json()["compose_yaml"]
        assert "io.hivora.zone: security-labs" in text
        # A normal app's compose may not pick the Labo zone.
        bad = client.post(f"{API}/apps/compose/plan", json={**body, "labs": False,
                                                            "zone": "security-labs"})  # fmt: skip
        assert bad.status_code == 409


# --- Lot 3: batch deploy (up to 25), each independent ---------------------------------------


def test_batch_deploys_many_and_isolates_failures(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        items = [{"template": "juice-shop", "inputs": {"web_port": 3000}},
                 {"template": "does-not-exist", "inputs": {}},
                 {"template": "webgoat", "inputs": {"web_port": 8080}}]  # fmt: skip
        r = client.post(f"{API}/apps/batch", json={"items": items})
        assert r.status_code == 202
        res = r.json()
        assert [x["ok"] for x in res] == [True, False, True]  # order kept, failure isolated
        assert res[1]["error"] == "template_not_found"
        for x in (res[0], res[2]):
            assert wait_job(client, x["app"]["job"]["id"])["status"] == "succeeded"
        assert len(client.get(f"{API}/apps").json()) == 2


def test_batch_has_a_hard_ceiling(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        items = [{"template": "juice-shop", "inputs": {"web_port": 3000 + i}} for i in range(101)]
        assert client.post(f"{API}/apps/batch", json={"items": items}).status_code == 422


def test_capacity_scales_with_host_memory(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        cap = client.get(f"{API}/apps/capacity/webgoat").json()
        assert cap["max_copies"] >= 1 and cap["cpus"] >= 1
        assert cap["memory_each_mb"] > 0 and cap["available_mb"] > 0
        assert cap["max_copies"] <= 100


def test_batch_refuses_labs_when_off(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=False))) as client:
        admin(client)
        items = [{"template": "juice-shop", "inputs": {"web_port": 3000}}]
        res = client.post(f"{API}/apps/batch", json={"items": items}).json()
        assert res[0]["ok"] is False and res[0]["error"] == "labs_disabled"


def test_plan_batch_previews_distinct_ips_ports_and_ordered_names(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        r = client.post(f"{API}/apps/plan/batch", json={"template": "juice-shop", "count": 3})
        assert r.status_code == 200
        rows = r.json()
        assert [x["name"] for x in rows] == ["juice-shop-1", "juice-shop-2", "juice-shop-3"]
        host_ports = [p["host_port"] for x in rows for p in x["ports"]]
        assert host_ports == [20000, 20001, 20002]  # high range, offset per copy
        ips = [ip for x in rows for ip in x["ips"]]
        assert len(ips) == len(set(ips)) and all(not x["conflicts"] for x in rows)
        # the preview's inputs are what actually deploys
        assert rows[1]["inputs"]["web_port"] == 20001


def test_plan_batch_gives_every_port_field_its_own_port(tmp_path: Path) -> None:
    """vulhub targets often publish several ports (ActiveMQ: 61616 + 8161): each copy gets
    a block of consecutive ports, one per field."""
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        body = {"template": "vulhub-activemq-cve-2015-5254", "count": 2}
        rows = client.post(f"{API}/apps/plan/batch", json=body).json()
        assert [x["inputs"] for x in rows] == [
            {"port_61616": 20000, "port_8161": 20001},
            {"port_61616": 20002, "port_8161": 20003},
        ]
        assert all(not x["conflicts"] for x in rows)


# --- Lot 6: one VPN for all labs, per-lab users --------------------------------------------


def test_labs_vpn_enable_and_per_lab_users(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        dep = client.post(f"{API}/apps", json={"template": "juice-shop", "name": "js",
                                               "inputs": {"web_port": 3000}}).json()  # fmt: skip
        assert wait_job(client, dep["job"]["id"])["status"] == "succeeded"

        assert client.get(f"{API}/labs/vpn").json()["enabled"] is False
        en = client.post(f"{API}/labs/vpn/enable")
        assert en.status_code == 202 and en.json()["app_id"] > 0

        names = {"names": ["alice", "bob", "alice", " "]}
        made = client.post(f"{API}/labs/vpn/students", json=names)
        assert made.status_code == 201 and len(made.json()) == 2  # deduplicated, blanks dropped
        bad = client.post(f"{API}/labs/vpn/students", json={"names": ["x;rm"]})
        assert bad.status_code == 422

        st = client.get(f"{API}/labs/vpn").json()
        assert st["enabled"] and [s["labs"] for s in st["students"]] == [[], []]  # roster first
        assert [lab["slug"] for lab in st["labs"]] == ["js"] and st["labs"][0]["students"] == 0

        alice, bob = made.json()

        def put(cid: int, labs: list[str]) -> int:
            url = f"{API}/labs/vpn/students/{cid}/labs"
            return client.put(url, json={"labs": labs}).status_code

        assert put(alice, ["js"]) == 204 and put(bob, ["nope"]) == 404
        assert client.post(f"{API}/labs/vpn/distribute").json() == {"assigned": 1}  # bob only
        st = client.get(f"{API}/labs/vpn").json()
        assert all(s["labs"] == ["js"] for s in st["students"]) and st["labs"][0]["students"] == 2

        assert client.post(f"{API}/labs/vpn/unassign").json() == {"removed": 2}
        st = client.get(f"{API}/labs/vpn").json()
        assert all(s["labs"] == [] for s in st["students"]) and st["labs"][0]["students"] == 0
        assert client.post(f"{API}/labs/vpn/distribute").json() == {"assigned": 2}

        cfg = client.get(f"{API}/labs/vpn/students/{alice}/config")
        assert cfg.status_code == 200 and "[Interface]" in cfg.text
        z = client.get(f"{API}/labs/vpn/configs.zip", params={"lab": "js"})
        zf = zipfile.ZipFile(io.BytesIO(z.content))
        assert sorted(zf.namelist()) == ["TUTO-SETUP.txt", "alice/alice.conf", "alice/alice.txt",
                                         "bob/bob.conf", "bob/bob.txt"]  # fmt: skip
        ip = st["labs"][0]["ip"]
        assert f"js : {ip}" in zf.read("alice/alice.txt").decode()
        assert "[Interface]" in zf.read("bob/bob.conf").decode()
        en = client.get(f"{API}/labs/vpn/configs.zip", params={"lang": "en"})
        assert "SETUP-GUIDE.txt" in zipfile.ZipFile(io.BytesIO(en.content)).namelist()


def test_balance_fills_the_emptiest_lab_and_keeps_assigned_students() -> None:
    assert balance([["a"], [], [], []], ["a", "b"]) == [None, "b", "a", "b"]
    assert balance([[]], []) == [None]  # no lab deployed: nothing to give


def test_student_access_is_enforced_per_host_by_the_server() -> None:
    vpn = SimpleNamespace(zones=["security-labs"])
    rights = {"internet": False, "lan": False, "zones": [], "hosts": ["10.254.252.5"]}
    peer = SimpleNamespace(address="10.254.251.2", access=rights)
    acc = access_of(peer, vpn, {"security-labs": ("10.254.252.0/24",)})  # type: ignore[arg-type]
    rules = wg.acl_script("wg0", [acc], ["10.254.252.0/24"]).splitlines()
    src = [r for r in rules if "-s 10.254.251.2/32" in r]
    assert src[0].endswith("-d 10.254.252.5/32 -j ACCEPT")  # its lab only
    assert src[1].endswith("-d 10.254.252.0/24 -j DROP")  # not the other labs
    assert src[-1].endswith("-j DROP")  # nor the LAN, nor the Internet
    assert not any("ACCEPT" in r for r in src[1:])


# --- VPN off again, and targets that must be scanned only behind it ---------------------------


def test_needs_vpn_target_waits_for_the_vpn_and_blocks_disabling(tmp_path: Path) -> None:
    import shutil
    import time

    cat = tmp_path / "catalog"
    shutil.copytree(REPO_TEMPLATES, cat)
    doc = yaml.safe_load((cat / "dvwa" / "template.yaml").read_text())
    doc["metadata"]["lab"]["needs_vpn"] = True
    (cat / "dvwa" / "template.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True))
    rt = _runtime(tmp_path, labs=True)
    rt = Runtime.build(rt.settings.model_copy(update={"catalog_dir": cat}),
                       gateway=FakeDockerGateway(), compose_cmd=FAKE,
                       compose_env={"FAKE_COMPOSE_MODE": "leak"})  # fmt: skip
    with TestClient(create_app(runtime=rt)) as client:
        admin(client)
        body = {"items": [{"template": "dvwa", "inputs": {"web_port": 8081}}]}
        assert client.post(f"{API}/apps/batch", json=body).json()[0]["error"] == "labs_vpn_required"
        js = client.post(f"{API}/apps", json={"template": "juice-shop", "name": "js",
                                              "inputs": {"web_port": 3000}}).json()  # fmt: skip
        assert wait_job(client, js["job"]["id"])["status"] == "succeeded"

        assert code(client.post(f"{API}/labs/vpn/disable")) == "labs_vpn_disabled"
        assert client.post(f"{API}/labs/vpn/enable").status_code == 202
        for _ in range(100):  # js, up before the VPN, stops publishing its port
            if "published: '3000'" not in client.get(f"{API}/apps/{js['app']['id']}/compose").text:
                break
            time.sleep(0.1)
        res = client.post(f"{API}/apps/batch", json=body).json()[0]
        assert res["ok"] and wait_job(client, res["app"]["job"]["id"])["status"] == "succeeded"
        refused = client.post(f"{API}/labs/vpn/disable")
        assert refused.status_code == 409 and code(refused) == "conflict"

        assert "published: '3000'" not in client.get(f"{API}/apps/{js['app']['id']}/compose").text
        assert client.delete(f"{API}/apps/{res['app']['app']['id']}").status_code == 202
        for _ in range(50):
            if len(client.get(f"{API}/apps").json()) == 2:
                break
            time.sleep(0.1)
        off = client.post(f"{API}/labs/vpn/disable")
        assert off.status_code == 202 and off.json() == {"labs": 1}
        for _ in range(100):
            if [a["name"] for a in client.get(f"{API}/apps").json()] == ["js"]:
                break
            time.sleep(0.1)
        assert client.get(f"{API}/labs/vpn").json()["enabled"] is False

        def compose() -> str:
            return client.get(f"{API}/apps/{js['app']['id']}/compose").text

        for _ in range(100):  # its port is published on the host again
            if "published: '3000'" in compose():
                break
            time.sleep(0.1)
        assert "published: '3000'" in compose()


def test_plan_and_batch_carry_custom_inputs_but_auto_assign_the_port(tmp_path: Path) -> None:
    with TestClient(create_app(runtime=_runtime(tmp_path, labs=True))) as client:
        admin(client)
        body = {
            "template": "juice-shop",
            "count": 2,
            "inputs": {"mode": "unsafe", "web_port": 9999},
        }
        prev = client.post(f"{API}/apps/plan/batch", json=body).json()
        assert [p["inputs"]["mode"] for p in prev] == ["unsafe", "unsafe"]  # custom value kept
        assert all(p["inputs"]["web_port"] != 9999 for p in prev)  # port auto-assigned, not ours
        items = [{"template": "juice-shop", "name": p["name"], "inputs": p["inputs"]} for p in prev]
        res = client.post(f"{API}/apps/batch", json={"items": items}).json()
        assert all(x["ok"] for x in res)
        for x in res:
            assert wait_job(client, x["app"]["job"]["id"])["status"] == "succeeded"
        compose = client.get(f"{API}/apps/{res[0]['app']['app']['id']}/compose").text
        assert "NODE_ENV: unsafe" in compose
