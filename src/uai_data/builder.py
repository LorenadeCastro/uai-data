"""Gera o site estático (pasta `site/`) que o GitHub Pages publica.

Para cada painel: executa as consultas, cifra os dados com a chave do painel (DK) e entrega
a DK, cifrada com a chave pública de cada usuário autorizado, no arquivo `auth/<usuário>.json`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

from . import access, crypto
from .config import ConfigError, Project
from .db import describe_catalog, get_engine
from .exports import dashboard_pdf, dashboard_xlsx
from .queries import collapse, run_card

WEB = Path(__file__).parent / "web"
LOCK_FILE = "access.lock.json"


# ----------------------------------------------------------------------------- lock (revogação)
def catalog_recipients(project: Project, org_id: str) -> list[str]:
    org = project.orgs[org_id]
    return sorted(
        u for u in {*org.admins, *org.members}
        if {"create", "edit"} & access.org_perms(org, u)
    ) if org.databases else []


def compute_lock(project: Project, old: dict) -> dict:
    """Calcula a época de cada chave.

    Quando alguém perde o acesso a um painel, a época sobe e a chave do painel muda no próximo
    build: o que a pessoa ainda tinha guardado deixa de abrir os dados novos.
    """
    new: dict[str, dict] = {}

    def resolve(key: str, authorized: list[str]) -> None:
        prev = old.get(key)
        epoch = prev["epoch"] if prev else 0
        if prev and set(prev["users"]) - set(authorized):
            epoch += 1
        new[key] = {"epoch": epoch, "users": sorted(authorized)}

    for dash_key in project.dashboards:
        resolve(f"dash:{dash_key}", access.viewers(project, dash_key))
        resolve(f"dashx:{dash_key}", access.downloaders(project, dash_key))
    for org_id in project.orgs:
        resolve(f"catalog:{org_id}", catalog_recipients(project, org_id))
    return new


def read_lock(root: Path) -> dict:
    path = root / LOCK_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_lock(root: Path, lock: dict) -> None:
    (root / LOCK_FILE).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_lock(project: Project) -> bool:
    """Atualiza access.lock.json no disco. Devolve True se mudou."""
    old = read_lock(project.root)
    new = compute_lock(project, old)
    if new != old:
        write_lock(project.root, new)
        return True
    return False


# ----------------------------------------------------------------------------- build
def auth_name(project: Project, login: str) -> str:
    return hashlib.sha256(f"{project.site.site_salt}:{login.lower()}".encode()).hexdigest()[:32]


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def build(project: Project, output: str | Path = "site", *, check_lock: bool = False) -> dict:
    master = os.environ.get("UAI_MASTER_KEY")
    if not master:
        raise ConfigError(
            "A variável UAI_MASTER_KEY não está definida. Gere uma com 'uai init' (ou 'uai keygen') "
            "e guarde-a em Settings → Secrets → Actions. Ela é o segredo que protege todos os painéis."
        )
    try:
        crypto.b64u_d(master)
    except Exception as exc:
        raise ConfigError("UAI_MASTER_KEY inválida — gere outra com 'uai keygen'.") from exc

    old_lock = read_lock(project.root)
    lock = compute_lock(project, old_lock)
    if lock != old_lock:
        if check_lock:
            raise ConfigError(
                "access.lock.json está desatualizado em relação às permissões. Rode 'uai lock' "
                "localmente e envie o arquivo no mesmo pull request. (O lock é o que faz a remoção "
                "de um acesso trocar a chave do painel.)"
            )
        write_lock(project.root, lock)

    out = Path(output)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc)

    wrapped: dict[str, dict[str, str]] = defaultdict(dict)       # login -> {id: DK cifrada}
    me: dict[str, dict] = {
        u: {"user": {"id": u, "name": usr.name, "email": usr.email}, "dashboards": [], "orgs": []}
        for u, usr in project.users.items()
    }
    engines: dict[str, object] = {}
    stats = {"dashboards": 0, "cards": 0, "users": len(project.users)}

    def engine(name: str):
        if name not in engines:
            engines[name] = get_engine(project.site, name)
        return engines[name]

    # ---- painéis
    for dash_key, dash in project.dashboards.items():
        viewers = access.viewers(project, dash_key)
        if not viewers:
            continue
        org = project.orgs[dash.organization]
        epoch = lock[f"dash:{dash_key}"]["epoch"] + dash.share_epoch
        dk = crypto.derive_key(master, f"dash:{dash_key}:{epoch}")
        did = crypto.derive_id(master, f"dash:{dash_key}")
        # chave própria dos arquivos baixáveis: quem só pode ver não a recebe
        ek = crypto.derive_key(master, f"dashx:{dash_key}:{lock[f'dashx:{dash_key}']['epoch'] + dash.share_epoch}")
        downloaders = access.downloaders(project, dash_key)

        data: dict[str, dict] = {}
        for card in dash.cards:
            db = engine(dash.database)
            cfg = project.site.databases[dash.database]
            try:
                data[card.id] = run_card(db, card, dash, timeout_s=cfg.statement_timeout_s,
                                         max_rows=project.site.max_rows_per_card)
            except ConfigError as exc:
                raise ConfigError(f"dashboards/{dash_key}.yml, card '{card.id}': {exc}") from exc
            _write(out / "c" / did / f"{card.id}.bin",
                   crypto.encrypt(dk, json.dumps(data[card.id], separators=(",", ":")).encode(), compress=True))
            stats["cards"] += 1

        spec = {
            "id": did, "key": dash_key, "title": dash.title, "description": dash.description,
            "organization": org.name, "updated": now.isoformat(), "filters": [f.model_dump() for f in dash.filters],
            "cards": [{**c.model_dump(exclude={"source", "where"}), "native": bool(c.source.sql)} for c in dash.cards],
            "edit_path": f"dashboards/{dash_key}.yml",
        }
        _write(out / "d" / did / "spec.bin", crypto.encrypt(dk, json.dumps(spec).encode(), compress=True))
        flat = {c.id: collapse(data[c.id], c) for c in dash.cards}     # visão sem filtros de tela
        _write(out / "x" / did / "dashboard.xlsx.bin", crypto.encrypt(ek, dashboard_xlsx(dash, flat, now)))
        _write(out / "x" / did / "dashboard.pdf.bin",
               crypto.encrypt(ek, dashboard_pdf(dash, flat, now, project.site.name)))

        for user in viewers:
            wrapped[user][did] = crypto.wrap_key(project.users[user].public_key, dk)
            if user in downloaders:
                wrapped[user][did + "x"] = crypto.wrap_key(project.users[user].public_key, ek)
            me[user]["dashboards"].append({
                "id": did, "key": dash_key, "title": dash.title, "description": dash.description,
                "organization": dash.organization, "tags": dash.tags,
                "perms": sorted(access.dashboard_perms(org, dash, user)),
            })
        stats["dashboards"] += 1

    # ---- catálogo de dados (só para quem pode criar/editar)
    for org_id, org in project.orgs.items():
        recipients = catalog_recipients(project, org_id)
        if not recipients:
            continue
        epoch = lock[f"catalog:{org_id}"]["epoch"]
        key = crypto.derive_key(master, f"catalog:{org_id}:{epoch}")
        cid = crypto.derive_id(master, f"catalog:{org_id}")
        try:
            tables = {db: describe_catalog(engine(db), project.site.catalog_schemas) for db in org.databases}
        except Exception as exc:  # noqa: BLE001 — catálogo é opcional; o build segue sem ele
            print(f"aviso: catálogo de '{org_id}' indisponível ({type(exc).__name__}: {exc})")
            continue
        _write(out / "k" / f"{cid}.bin", crypto.encrypt(key, json.dumps(tables).encode(), compress=True))
        for user in recipients:
            wrapped[user][cid] = crypto.wrap_key(project.users[user].public_key, key)
            me[user].setdefault("catalogs", {})[org_id] = cid

    # ---- resumo de organizações por usuário
    for org_id, org in project.orgs.items():
        for user in {*org.admins, *org.members}:
            admin = access.is_admin(org, user)
            entry = {
                "id": org_id, "name": org.name, "admin": admin,
                "profile": "admin" if admin else org.members[user],
                "perms": sorted(access.org_perms(org, user)),
                "catalog": me[user].get("catalogs", {}).get(org_id),
                "databases": org.databases,
            }
            if admin:     # só o administrador enxerga a lista de pessoas e perfis
                entry["profiles"] = org.profiles
                entry["members"] = [
                    {"id": u, "name": project.users[u].name, "profile": "admin" if u in org.admins else org.members[u]}
                    for u in sorted({*org.admins, *org.members})
                ]
            me[user]["orgs"].append(entry)

    # ---- um arquivo de autenticação por usuário
    for login, user in project.users.items():
        me_key = crypto.derive_key(master, f"me:{login}")
        blob = {
            "v": 1,
            "kdf": {"salt": user.kdf.salt, "iter": user.kdf.iter},
            "priv": user.enc_private_key,
            "keys": {"@me": crypto.wrap_key(user.public_key, me_key), **wrapped[login]},
        }
        name = auth_name(project, login)
        _write(out / "auth" / f"{name}.json", json.dumps(blob, separators=(",", ":")))
        _write(out / "auth" / f"{name}.me.bin", crypto.encrypt(me_key, json.dumps(me[login]).encode(), compress=True))

    _copy_static(out, project, now)
    return stats


def _copy_static(out: Path, project: Project, now: dt.datetime) -> None:
    for item in WEB.iterdir():
        target = out / item.name
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
    try:
        from plotly.offline import get_plotlyjs
        _write(out / "plotly.min.js", get_plotlyjs())
    except Exception as exc:
        raise ConfigError("Não consegui obter o plotly.min.js do pacote 'plotly'.") from exc
    s = project.site
    _write(out / "config.json", json.dumps({
        "name": s.name, "tagline": s.tagline, "locale": s.locale, "currency": s.currency,
        "csvSep": s.csv_sep, "csvDecimal": s.csv_decimal, "salt": s.site_salt,
        "repo": s.repo, "branch": s.branch, "generated": now.isoformat(),
    }))
    _write(out / ".nojekyll", "")
