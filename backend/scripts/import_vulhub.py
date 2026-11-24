"""Turn vulhub environments (https://github.com/vulhub/vulhub, MIT) into security-lab templates.

    git clone --depth 1 https://github.com/vulhub/vulhub /tmp/vulhub
    uv run python scripts/import_vulhub.py /tmp/vulhub
    uv run python scripts/import_vulhub.py --retouch   # names and summaries of the imported ones

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

VERSION = "1.1.0"
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


PRODUCTS = {  # vulhub's app slug -> the product's name, as its editor writes it
    "1panel": "1Panel",
    "adminer": "Adminer",
    "adobe-coldfusion": "Adobe ColdFusion",
    "aj-report": "AJ-Report",
    "apache-activemq": "Apache ActiveMQ",
    "apache-airflow": "Apache Airflow",
    "apache-couchdb": "Apache CouchDB",
    "apache-cxf": "Apache CXF",
    "apache-druid": "Apache Druid",
    "apache-flink": "Apache Flink",
    "apache-hertzbeat": "Apache HertzBeat",
    "apache-hugegraph": "Apache HugeGraph",
    "apache-jmeter": "Apache JMeter",
    "apache-kafka": "Apache Kafka",
    "apache-linkis": "Apache Linkis",
    "apache-log4j": "Apache Log4j 2",
    "apache-ofbiz": "Apache OFBiz",
    "apache-rocketmq": "Apache RocketMQ",
    "apache-shiro": "Apache Shiro",
    "apache-skywalking": "Apache SkyWalking",
    "apache-solr": "Apache Solr",
    "apache-spark": "Apache Spark",
    "apache-struts2": "Apache Struts 2",
    "apache-superset": "Apache Superset",
    "apache-tomcat": "Apache Tomcat",
    "apereo-cas": "Apereo CAS",
    "aria2": "Aria2",
    "cms-made-simple": "CMS Made Simple",
    "comfyui": "ComfyUI",
    "confluence": "Atlassian Confluence",
    "craftcms": "CraftCMS",
    "dataease": "DataEase",
    "discuz": "Discuz!",
    "django": "Django",
    "drupal": "Drupal",
    "ecshop": "ECShop",
    "elasticsearch": "Elasticsearch",
    "elfinder": "elFinder",
    "erlang-otp-ssh": "Erlang/OTP SSH",
    "fastjson": "Fastjson",
    "geoserver": "GeoServer",
    "git": "Git",
    "gitea": "Gitea",
    "glassfish": "GlassFish",
    "gnu-inetutils": "GNU InetUtils",
    "gogs": "Gogs",
    "gotenberg": "Gotenberg",
    "gradio": "Gradio",
    "grafana": "Grafana",
    "hadoop-yarn": "Hadoop YARN",
    "influxdb": "InfluxDB",
    "jackson-databind": "Jackson Databind",
    "java-rmi": "Java RMI",
    "jboss": "JBoss",
    "jenkins": "Jenkins",
    "jimureport": "JeecgBoot JimuReport",
    "joomla": "Joomla",
    "jupyter": "Jupyter",
    "kibana": "Kibana",
    "kkfileview": "kkFileView",
    "langflow": "Langflow",
    "laravel": "Laravel",
    "laravel-livewire": "Laravel Livewire",
    "libssh": "libssh",
    "liferay-portal": "Liferay Portal",
    "magento": "Magento",
    "metabase": "Metabase",
    "metersphere": "MeterSphere",
    "mini-httpd": "ACME mini_httpd",
    "mojarra-jsf": "Mojarra JSF",
    "mysql": "MySQL",
    "n8n": "n8n",
    "nacos": "Alibaba Nacos",
    "next-js": "Next.js",
    "nexus-repository-manager": "Nexus Repository Manager",
    "nginx-ui": "Nginx UI",
    "ntopng": "ntopng",
    "openclaw": "OpenClaw",
    "openfire": "Openfire",
    "openprinting-cups-browsed": "CUPS cups-browsed",
    "opensmtpd": "OpenSMTPD",
    "openssl": "OpenSSL",
    "opentsdb": "OpenTSDB",
    "owncloud": "ownCloud",
    "pgadmin": "pgAdmin",
    "php-fpm": "PHP-FPM",
    "phpmyadmin": "phpMyAdmin",
    "phpunit": "PHPUnit",
    "polkit-pkexec": "Polkit pkexec",
    "postgresql": "PostgreSQL",
    "python": "Python aiohttp",
    "react": "React",
    "redis": "Redis",
    "rocket-chat": "Rocket.Chat",
    "ruby-on-rails": "Ruby on Rails",
    "saltstack": "SaltStack",
    "scrapyd": "Scrapyd",
    "showdoc": "ShowDoc",
    "spring": "Spring",
    "spring-cloud-function": "Spring Cloud Function",
    "spring-cloud-gateway": "Spring Cloud Gateway",
    "spring-data-commons": "Spring Data Commons",
    "spring-data-rest": "Spring Data REST",
    "spring-messaging": "Spring Messaging",
    "spring-security-oauth2": "Spring Security OAuth2",
    "spring-webflow": "Spring WebFlow",
    "springboot-h2-database": "H2 Database",
    "supervisor": "Supervisor",
    "teamcity": "JetBrains TeamCity",
    "thinkphp": "ThinkPHP",
    "uwsgi": "uWSGI",
    "vite": "Vite",
    "weblogic": "Oracle WebLogic",
    "webmin": "Webmin",
    "wordpress": "WordPress",
    "xstream": "XStream",
    "xxl-job": "XXL-JOB",
}
# vulhub's tags that name a kind of flaw (the others are families: cms, database…), most
# specific first: the summary names them in this order.
VULNS = {
    "sql-injection": ("Injection SQL", "SQL injection"),
    "deserialization": ("Désérialisation non sûre", "Insecure deserialization"),
    "expression-injection": ("Injection d'expression", "Expression injection"),
    "ssti": ("Injection de template (SSTI)", "Template injection (SSTI)"),
    "environment-injection": ("Injection de variables d'environnement", "Environment injection"),
    "xxe": ("Entité externe XML (XXE)", "XML external entity (XXE)"),
    "ssrf": ("Requête forgée côté serveur (SSRF)", "Server-side request forgery (SSRF)"),
    "path-traversal": ("Traversée de répertoires", "Path traversal"),
    "file-upload": ("Envoi de fichier arbitraire", "Arbitrary file upload"),
    "file-deletion": ("Suppression de fichier arbitraire", "Arbitrary file deletion"),
    "auth-bypass": ("Contournement d'authentification", "Authentication bypass"),
    "hard-coding": ("Secret codé en dur", "Hard-coded secret"),
    "info-disclosure": ("Fuite d'informations", "Information disclosure"),
    "xss": ("Cross-site scripting (XSS)", "Cross-site scripting (XSS)"),
    "privilege-escalation": ("Élévation de privilèges", "Privilege escalation"),
    "dos": ("Déni de service", "Denial of service"),
    "rce": ("Exécution de code à distance", "Remote code execution"),
}
PRE_AUTH = re.compile(r"\b(pre-?auth\w*|unauth\w*|without auth\w*)\b", re.I)
POST_AUTH = re.compile(r"\b(post-?auth\w*|authenticated)\b", re.I)


def product(app: str) -> str:
    return PRODUCTS.get(app) or app.replace("-", " ").title()


def summary(tags: list[str], title: str) -> dict[str, str]:
    """The flaw in plain words, FR and EN, from vulhub's tags (and its title's pre/post-auth)."""
    found = [VULNS[t] for t in VULNS if t in tags]
    if not found:
        return {"fr": title, "en": title}
    # "A · B → remote code execution": what the flaw leads to comes last, after an arrow.
    *first, last = found
    if first and last == VULNS["rce"]:
        fr = " · ".join(f for f, _ in first) + " → exécution de code"
        en = " · ".join(e for _, e in first) + " → code execution"
    else:
        fr, en = " · ".join(f for f, _ in found), " · ".join(e for _, e in found)
    if "auth-bypass" in tags:  # says it already
        pass
    elif PRE_AUTH.search(title):
        fr, en = f"{fr}, sans authentification", f"{en}, unauthenticated"
    elif POST_AUTH.search(title):
        fr, en = f"{fr}, compte requis", f"{en}, authenticated"
    return {"fr": fr, "en": en}


def present(meta: dict[str, Any], app: str, title: str, tags: list[str]) -> None:
    """How a target shows in the panel: the product as its name, the flaw as its summary,
    vulhub's own title as its description; no difficulty (vulhub does not rate them)."""
    meta["name"] = product(app)
    meta["description"] = f"{title} (vulhub)."
    lab = meta["lab"]
    lab["tech"] = sorted(t for t in tags if t != app)
    lab["summary"] = summary(lab["tech"], title)
    lab.pop("difficulty", None)


def retouch() -> int:
    """Re-present the templates already imported (no clone, no Docker Hub)."""
    yaml.add_representer(str, _str, Dumper=yaml.SafeDumper)
    n = 0
    for path in sorted(OUT.glob("vulhub-*/template.yaml")):
        tpl = yaml.safe_load(path.read_text())
        meta = tpl["metadata"]
        # Before: "<app> — <title> (vulhub)."; now: "<title> (vulhub).".
        title = meta["description"].split(" — ", 1)[-1].removesuffix(" (vulhub).")
        app = meta["tags"][1]
        present(meta, app, title, [*meta["lab"]["tech"], app])
        meta["version"] = VERSION
        Template.model_validate(tpl)
        path.write_text(yaml.safe_dump(tpl, sort_keys=False, allow_unicode=True, width=1000))
        n += 1
    print(f"{n} templates retouched")
    return 0


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
                "solution": {lang: f"{note} {REPO + env['path']}\n" + solution(readme)
                             for lang, note in NOTE.items()},  # fmt: skip
            },
        },
        "requirements": {"arch": sorted(arch)},
        "form": {"basic": fields} if fields else {},
        "services": services,
        "update": {"strategy": "manual"},
    }
    present(tpl["metadata"], slugify(env["app"]), env["name"], [slugify(t) for t in tags])
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
    sys.exit(retouch() if sys.argv[1] == "--retouch" else main(Path(sys.argv[1])))
