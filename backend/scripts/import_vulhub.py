"""Turn vulhub environments (https://github.com/vulhub/vulhub, MIT) into security-lab templates.

    git clone --depth 1 https://github.com/vulhub/vulhub /tmp/vulhub
    uv run python scripts/import_vulhub.py /tmp/vulhub

Writes ``templates/vulhub-<path>/template.yaml`` for every environment made only of images
(no ``build:``, no file of the repository mounted, no option the schema lacks), each image
pinned by its Docker Hub digest. Re-run it to refresh; bump VERSION when the output changes,
then ``HIVORA_UPDATE_TEMPLATE_LOCK=1 pytest tests/test_templates.py``.
"""

import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from hivora.templates.schema import Template

VERSION = "1.0.0"
OUT = Path(__file__).parents[2] / "templates"
REPO = "https://github.com/vulhub/vulhub/tree/master/"
# ponytail: options we cannot translate make the whole environment skipped, not half-imported.
UNSUPPORTED = {"build", "privileged", "entrypoint", "working_dir", "hostname", "env_file",
               "ulimits", "cap_add", "network_mode", "pid", "devices", "security_opt"}  # fmt: skip
IGNORED = {"restart", "container_name", "labels", "networks", "links", "init", "expose"}
DATABASES = ("mysql", "mariadb", "postgres", "mongo", "mssql", "oracle", "elasticsearch")
CACHES = ("redis", "memcached")
NOTE = {
    "fr": "Adresse : IP:port affichés par le panel (les ports du guide sont ceux d'origine de "
    "vulhub), ou l'IP du lab sur le port d'origine via le VPN labo. Guide d'origine (anglais) :",
    "en": "Address: the IP:port shown by the panel (the guide's ports are vulhub's original "
    "ones), or the lab's IP on the original port through the labs VPN. Original guide:",
}


class Skip(Exception):
    pass


CACHE = Path()  # in the vulhub clone (set by main): a re-run skips the Hub
_digests: dict[str, tuple[str, list[str]]] = {}


def hub(url: str) -> dict[str, Any]:
    """GET a Docker Hub API page, waiting out its rate limit."""
    for _ in range(10):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise Skip(f"{url}: {e}") from None
            data = {"detail": "Rate limit exceeded"}
        if "Rate limit" not in str(data.get("detail", "")):
            return data
        time.sleep(30)
    raise Skip(f"{url}: still rate-limited")


def digest(image: str) -> tuple[str, list[str]]:
    """The tag's digest and its architectures, from the Docker Hub API."""
    if image not in _digests:
        repo, _, tag = image.partition(":")
        tag = tag or "latest"
        if "/" not in repo:
            repo = f"library/{repo}"
        if "." in repo.split("/")[0]:
            raise Skip(f"not on Docker Hub: {image}")
        data = hub(f"https://hub.docker.com/v2/repositories/{repo}/tags/{tag}")
        images = data.get("images", [])
        arches = sorted({i["architecture"] for i in images} & {"amd64", "arm64"})
        if not data.get("digest") and len(images) == 1:  # old single-arch push: no index
            data["digest"] = images[0].get("digest")
        if not data.get("digest") or not arches:
            raise Skip(f"{image}: no digest or no amd64/arm64 build")
        _digests[image] = (f"{tag}@{data['digest']}", arches)
        CACHE.write_text(json.dumps(_digests, indent=1, sort_keys=True))
    return _digests[image]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def solution(readme: str) -> str:
    """vulhub's Markdown in the panel's guide format (``# `` titles, ``$ `` code lines)."""
    out: list[str] = []
    code = False
    for line in readme.splitlines():
        if line.lstrip().startswith("```"):
            code = not code
            continue
        if code:
            if line.strip():
                out.append("$ " + line.rstrip())
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line).strip()  # images live in the repo
        if "README.zh-cn.md" in line:
            continue  # the link to the Chinese version
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        if m := re.match(r"#{1,6}\s+(.*)", line):
            out.append("# " + m.group(1))
        elif line:
            out.append(line.rstrip())
    if out and out[0].startswith("# "):
        out.pop(0)  # the title: the template's name already
    return "\n".join(out) + "\n"


def env_of(svc: dict[str, Any]) -> dict[str, str | int | bool]:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        env = dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    out = {}
    for k, v in env.items():
        v = "" if v is None else v
        if isinstance(v, float) or "${" in str(v) or "{{" in str(v):
            raise Skip(f"environment {k}")
        out[str(k)] = v
    return out


def parse_port(spec: Any) -> tuple[int, int, str]:
    """(host, container, protocol) of a compose short port."""
    text, _, proto = str(spec).partition("/")
    parts = text.split(":")
    if not all(p.isdigit() for p in parts[-2:]) or len(parts) > 3:
        raise Skip(f"port {spec}")
    return int(parts[-2] if len(parts) > 1 else parts[-1]), int(parts[-1]), proto or "tcp"


def convert(env: dict[str, Any], root: Path) -> dict[str, Any]:
    d = root / env["path"]
    compose = yaml.safe_load((d / "docker-compose.yml").read_text())
    readme = (d / "README.md").read_text() if (d / "README.md").exists() else ""
    services_in: dict[str, dict[str, Any]] = compose["services"]
    names = {n: slugify(n) for n in services_in}
    main = next((n for n, s in services_in.items() if s.get("ports")), next(iter(services_in)))
    fields: list[dict[str, Any]] = []
    services: dict[str, Any] = {}
    arch = {"amd64", "arm64"}
    web: str | None = None
    for name, svc in services_in.items():
        if bad := (set(svc) - IGNORED - {"image", "ports", "environment", "command",
                   "depends_on", "healthcheck", "user", "volumes", "tty", "shm_size"}):  # fmt: skip
            raise Skip(f"{name}: {sorted(bad)}")
        if bad := set(svc) & UNSUPPORTED:
            raise Skip(f"{name}: {sorted(bad)}")
        tag, arches = digest(svc["image"])
        arch &= set(arches)
        image = svc["image"].partition(":")[0]
        base = image.rsplit("/", 1)[-1]
        role = ("main" if name == main else "database" if base.startswith(DATABASES)
                else "cache" if base.startswith(CACHES) else "sidecar")  # fmt: skip
        out: dict[str, Any] = {"role": role, "image": image, "tag": tag, "frozen": True}
        if env_vars := env_of(svc):
            out["env"] = env_vars
        if "command" in svc:
            out["command"] = svc["command"]
        if deps := svc.get("depends_on"):
            out["depends_on"] = [names[x] for x in deps]
        for key in ("healthcheck", "user", "tty"):
            if key in svc:
                out[key] = svc[key]
        if "shm_size" in svc:
            out["shm_size"] = str(svc["shm_size"]).lower()
        vols = []
        for v in svc.get("volumes") or []:
            src, _, target = str(v).partition(":")
            if not target or src.startswith((".", "/", "~")):
                raise Skip(f"volume {v}")
            vols.append({"name": slugify(src), "target": target.split(":")[0]})
        if vols:
            out["volumes"] = vols
        ports = []
        for p in svc.get("ports") or []:
            host, container, proto = parse_port(p)
            fid = f"port_{container}" + ("" if proto == "tcp" else f"_{proto}")
            if name != main:
                fid = f"{slugify(name).replace('-', '_')}_{fid}"
            is_web = container == 80 or bool(re.search(rf"https?://[^\s/]*:{host}\b", readme))
            fields.append({"id": fid, "group": {"fr": "Accès", "en": "Access"},
                           "label": f"{name} {container}/{proto}", "type": "port",
                           "default": host})  # fmt: skip
            ports.append({"container": container, "host": f"{{{{ form.{fid} }}}}",
                          "protocol": proto, "purpose": "web" if is_web else "other",
                          "exposure": "lan"})  # fmt: skip
            if is_web and web is None:
                web = f"http://{{{{ host.lan_ip }}}}:{{{{ form.{fid} }}}}"
        if ports:
            out["ports"] = ports
        services[names[name]] = out
    if not arch:
        raise Skip("no common architecture")
    tags = env.get("tags", [])
    slug = ("vulhub-" + slugify(env["path"]))[:63].rstrip("-")
    tpl: dict[str, Any] = {
        "apiVersion": "hivora/v1",
        "kind": "Template",
        "metadata": {
            "slug": slug,
            "name": env["name"],
            "version": VERSION,
            "category": "security-lab",
            "tags": ["vulhub", slugify(env["app"])],
            "description": f"{env['app']} — {env['name']} (vulhub).",
            "links": {"site": REPO + env["path"]},
            "maintainer": "vulhub",
            "license": "MIT (vulhub)",
            "source": REPO + env["path"],
            "lab": {
                "phase": "installation" if "Privilege Escalation" in tags else "exploitation",
                "cves": [c for c in env.get("cve", []) if re.fullmatch(r"CVE-\d{4}-\d{4,}", c)],
                "os": ["linux"],
                "tech": sorted({slugify(t) for t in tags} | {slugify(env["app"])}),
                "difficulty": "medium",
                "summary": env["name"],
                "solution": {lang: f"{note} {REPO + env['path']}\n" + solution(readme)
                             for lang, note in NOTE.items()},  # fmt: skip
            },
        },
        "requirements": {"arch": sorted(arch)},
        "form": {"basic": fields} if fields else {},
        "services": services,
        "update": {"strategy": "manual"},
    }
    if web:
        tpl["access"] = {"web": web}
    Template.model_validate(tpl)
    return tpl


def _str(dumper: yaml.Dumper, s: str) -> yaml.Node:
    style = "|" if "\n" in s else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


def main(root: Path) -> int:
    global CACHE
    CACHE = root / ".hivora-digests.json"
    if CACHE.exists():
        _digests.update({k: tuple(v) for k, v in json.loads(CACHE.read_text()).items()})
    yaml.add_representer(str, _str, Dumper=yaml.SafeDumper)
    envs = tomllib.loads((root / "environments.toml").read_text())["environment"]
    done, skipped = 0, []
    for env in envs:
        try:
            tpl = convert(env, root)
        except Skip as e:
            skipped.append(f"{env['path']}: {e}")
            continue
        except Exception as e:  # schema refusal: report, keep going
            skipped.append(f"{env['path']}: {type(e).__name__} {str(e).splitlines()[0]}")
            continue
        dest = OUT / tpl["metadata"]["slug"] / "template.yaml"
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(yaml.safe_dump(tpl, sort_keys=False, allow_unicode=True, width=1000))
        done += 1
    print(f"{done} templates written, {len(skipped)} skipped:")
    print("\n".join(f"  {s}" for s in skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
