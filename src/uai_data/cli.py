"""Linha de comando do Uai Data. Os comandos seguem o padrão do MkDocs e ficam em inglês."""

from __future__ import annotations

import http.server
import os
import secrets
import socketserver
import time
from functools import partial
from pathlib import Path

import typer
import yaml

from . import __version__, crypto, scaffold
from .builder import build as build_site
from .builder import compute_lock, read_lock, update_lock
from .config import VIZ_TYPES, ConfigError, Project, dump_yaml
from .db import get_engine
from .guard import check_pull_request
from .queries import run_card

app = typer.Typer(help="Uai Data — painéis de dados open source, 100% Python, sem servidor.",
                  no_args_is_help=True, add_completion=False)
user_app = typer.Typer(help="Gerencia usuários (login e senha).", no_args_is_help=True)
org_app = typer.Typer(help="Gerencia organizações, perfis e membros.", no_args_is_help=True)
dash_app = typer.Typer(help="Cria painéis.", no_args_is_help=True)
app.add_typer(user_app, name="user")
app.add_typer(org_app, name="org")
app.add_typer(dash_app, name="dashboard")

ROOT_OPT = typer.Option(Path("."), "--root", "-C", help="Pasta do projeto.")


# ----------------------------------------------------------------------------- utilidades
def _load_dotenv(root: Path) -> None:
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _project(root: Path) -> Project:
    _load_dotenv(root)
    try:
        return Project.load(root)
    except ConfigError as exc:
        _fail(str(exc))


def _password(env_var: str | None, prompt: str = "Senha") -> str:
    if env_var:
        value = os.environ.get(env_var)
        if not value:
            _fail(f"A variável {env_var} não está definida.")
    else:
        value = typer.prompt(prompt, hide_input=True, confirmation_prompt=True)
    if len(value) < 10:
        _fail("Use uma senha com pelo menos 10 caracteres (frase longa é melhor que símbolos).")
    return value


def _read(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _users_file(root: Path) -> Path:
    return root / "access" / "users.yml"


def _save_user(root: Path, login: str, entry: dict) -> None:
    data = _read(_users_file(root))
    data.setdefault("users", {})[login] = entry
    dump_yaml(_users_file(root), data)


def _user_entry(name, email, github, keys: crypto.UserKeys) -> dict:
    entry = {"name": name}
    if email:
        entry["email"] = email
    if github:
        entry["github"] = github
    entry.update(public_key=keys.public_key, kdf={"salt": keys.kdf_salt, "iter": keys.kdf_iter},
                 enc_private_key=keys.enc_private_key)
    return entry


def _after_access_change(root: Path) -> None:
    project = _project(root)
    if update_lock(project):
        typer.echo("access.lock.json atualizado — inclua-o no commit.")


def _iterations(root: Path) -> int:
    try:
        return int((_read(root / "uai.yml")).get("pbkdf2_iterations", 600_000))
    except (TypeError, ValueError):
        return 600_000


# ----------------------------------------------------------------------------- comandos
@app.callback(invoke_without_command=True)
def _main(version: bool = typer.Option(False, "--version", help="Mostra a versão.")) -> None:
    if version:
        typer.echo(f"uai-data {__version__}")
        raise typer.Exit()


@app.command()
def keygen() -> None:
    """Gera um UAI_MASTER_KEY (segredo do projeto)."""
    typer.echo(crypto.new_master_key())


@app.command()
def init(
    path: Path = typer.Argument(Path("meus-paineis"), help="Pasta do novo projeto."),
    template: str = typer.Option("demo", help="demo (vendas, sem PostgreSQL) ou siafi (dados-siafi-2026 + PostgreSQL)."),
    name: str = typer.Option("Uai Data", help="Nome do site."),
    admin: str = typer.Option("admin", help="Login do administrador."),
    admin_name: str = typer.Option("Administrador", help="Nome do administrador."),
    github: str = typer.Option("", help="Usuário do administrador no GitHub."),
    repo: str = typer.Option("", help="dono/repositório no GitHub."),
    org: str = typer.Option(None, help="Id da organização (padrão: demo, ou splor no template siafi)."),
    org_name: str = typer.Option(None, help="Nome da organização."),
    password_env: str = typer.Option(None, help="Variável com a senha do admin (sem prompt)."),
    sample_users: bool = typer.Option(True, help="Cria usuários de exemplo (editor, analista e leitor)."),
    uai_git: str = typer.Option(None, "--uai-git", help="De onde instalar o uai-data: URL git do seu repositório ou caminho local. Padrão: PyPI."),
) -> None:
    """Cria um projeto completo. Com --template demo funciona na hora, sem PostgreSQL."""
    if template not in ("demo", "siafi"):
        _fail("--template precisa ser 'demo' ou 'siafi'.")
    siafi = template == "siafi"
    org = org or ("splor" if siafi else "demo")
    org_name = org_name or ("SPLOR-MG" if siafi else "Organização Demo")
    if path.exists() and any(path.iterdir()):
        _fail(f"A pasta {path} já existe e não está vazia.")
    path.mkdir(parents=True, exist_ok=True)
    password = _password(password_env, f"Senha do administrador '{admin}'")

    def put(rel: str, text: str) -> None:
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    fill = lambda t: (t.replace("__NAME__", name).replace("__REPO__", repo or "dono/repositorio")
                      .replace("__SALT__", secrets.token_hex(8)).replace("__ADMIN__", admin)
                      .replace("__ORG__", org).replace("__ORG_NAME__", org_name))
    slug = path.resolve().name.lower().replace(" ", "-")
    put("uai.yml", fill(scaffold.SIAFI_UAI_YML if siafi else scaffold.UAI_YML))
    if uai_git is None:
        dep = 'uai-data = ">=0.1"'
    elif uai_git.startswith(("/", ".", "~")):
        dep = f'uai-data = {{ path = "{Path(uai_git).expanduser().resolve()}", develop = true }}'
    else:
        dep = f'uai-data = {{ git = "{uai_git}", branch = "main" }}'
    put("pyproject.toml", scaffold.PYPROJECT.replace("__SLUG__", slug).replace("__UAI_DEP__", dep))
    put(".gitignore", scaffold.GITIGNORE)
    put(".github/workflows/build.yml", scaffold.SIAFI_WORKFLOW if siafi else scaffold.BUILD_WORKFLOW)
    put(".github/workflows/guard.yml", scaffold.GUARD_WORKFLOW)
    put(".github/CODEOWNERS", scaffold.CODEOWNERS.replace("__GITHUB__", github or "SEU-USUARIO-GITHUB"))
    if siafi:
        put("dashboards/%s/execucao.yml" % org, fill(scaffold.SIAFI_EXEC))
        put("dashboards/%s/receita.yml" % org, fill(scaffold.SIAFI_RECEITA))
        put("dashboards/%s/restos-a-pagar.yml" % org, fill(scaffold.SIAFI_RP))
        put("docker-compose.yml", scaffold.DOCKER_COMPOSE)
    else:
        put("dashboards/%s/vendas.yml" % org, fill(scaffold.DASHBOARD_YML))

    iters = 600_000
    typer.echo("Gerando chaves do administrador (leva alguns segundos)…")
    users = {admin: _user_entry(admin_name, None, github or None, crypto.new_user_keys(password, iters))}
    members = {}
    printed = []
    if sample_users:
        for login, nm, profile in (("ana", "Ana (editora)", "editor"), ("caio", "Caio (analista)", "analyst"),
                                   ("bia", "Bia (leitora)", "viewer")):
            pw = scaffold.new_password()
            users[login] = _user_entry(nm, None, None, crypto.new_user_keys(pw, iters))
            members[login] = profile
            printed.append((login, profile, pw))
    dump_yaml(path / "access" / "users.yml", {"users": users})
    member_text = "\n".join(f"  {k}: {v}" for k, v in members.items()) or "  {}"
    put(f"access/{org}.yml", fill(scaffold.ORG_YML.replace("__DBS__", "siafi" if siafi else "demo")
                                  .replace("__MEMBERS__", member_text)))

    master = crypto.new_master_key()
    if siafi:
        put(".env", f"UAI_MASTER_KEY={master}\nUAI_DB_SIAFI=postgresql://postgres:postgres@localhost:5432/siafi\n")
        nxt = (f"  cd {path} && poetry install\n  docker compose up -d\n"
               f"  poetry run uai load CAMINHO/dados-siafi-2026 --database siafi\n  poetry run uai serve")
    else:
        scaffold.create_demo_db(path / "demo" / "vendas.db")
        put(".env", f"UAI_MASTER_KEY={master}\nUAI_DB_DEMO=sqlite:///demo/vendas.db\n")
        nxt = f"  cd {path} && poetry install && poetry run uai serve"
    _after_access_change(path)

    typer.secho(f"\nProjeto criado em {path}/", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"\nUAI_MASTER_KEY (guarde em Settings → Secrets → Actions; também está em {path}/.env):\n  {master}\n")
    if printed:
        typer.echo("Usuários de exemplo (senhas aparecem só agora):")
        for login, profile, pw in printed:
            typer.echo(f"  {login:<6} perfil {profile:<8} senha {pw}")
    typer.echo(f"\nPróximo passo:\n{nxt}")


@app.command()
def check(root: Path = ROOT_OPT,
          connect: bool = typer.Option(False, "--connect", help="Também testa o banco e executa cada card.")) -> None:
    """Valida a configuração (e, com --connect, as consultas) antes de publicar."""
    project = _project(root)
    typer.secho(f"✓ configuração válida: {len(project.users)} usuários, {len(project.orgs)} organizações, "
                f"{len(project.dashboards)} painéis", fg=typer.colors.GREEN)
    if read_lock(project.root) != compute_lock(project, read_lock(project.root)):
        typer.secho("! access.lock.json desatualizado — rode 'uai lock'", fg=typer.colors.YELLOW)
    if not connect:
        return
    engines: dict = {}
    failed = False
    for key, dash in project.dashboards.items():
        try:
            engines.setdefault(dash.database, get_engine(project.site, dash.database))
        except ConfigError as exc:
            _fail(str(exc))
        for card in dash.cards:
            t0 = time.time()
            try:
                out = run_card(engines[dash.database], card, dash,
                               timeout_s=project.site.databases[dash.database].statement_timeout_s,
                               max_rows=project.site.max_rows_per_card)
                typer.echo(f"  ✓ {key} · {card.id}: {len(out['rows'])} linhas em {time.time() - t0:.1f}s")
            except Exception as exc:  # noqa: BLE001
                failed = True
                typer.secho(f"  ✗ {key} · {card.id}: {exc}", fg=typer.colors.RED)
    if failed:
        raise typer.Exit(1)


@app.command()
def lock(root: Path = ROOT_OPT, check_only: bool = typer.Option(False, "--check", help="Só confere.")) -> None:
    """Atualiza access.lock.json (é ele que troca a chave de um painel quando alguém perde o acesso)."""
    project = _project(root)
    if check_only:
        old = read_lock(project.root)
        if compute_lock(project, old) != old:
            _fail("access.lock.json desatualizado — rode 'uai lock'.")
        typer.echo("✓ lock em dia")
    else:
        typer.echo("access.lock.json atualizado." if update_lock(project) else "Lock já estava em dia.")


@app.command()
def build(root: Path = ROOT_OPT, output: Path = typer.Option(Path("site"), "--output", "-o"),
          check_lock: bool = typer.Option(False, "--check-lock", help="Falha se o lock estiver desatualizado (CI).")) -> None:
    """Executa as consultas e gera o site estático (pasta site/)."""
    project = _project(root)
    try:
        stats = build_site(project, root / output if not output.is_absolute() else output, check_lock=check_lock)
    except ConfigError as exc:
        _fail(str(exc))
    typer.secho(f"✓ site gerado em {output}/ — {stats['dashboards']} painéis, {stats['cards']} cards, "
                f"{stats['users']} usuários", fg=typer.colors.GREEN)


@app.command()
def serve(root: Path = ROOT_OPT, port: int = typer.Option(8000, "--port", "-p"),
          output: Path = typer.Option(Path("site"), "--output", "-o"),
          rebuild: bool = typer.Option(True, "--build/--no-build", help="Gera o site antes de servir.")) -> None:
    """Gera o site e o serve localmente em http://localhost:8000 (só para testar)."""
    if rebuild:
        build(root=root, output=output, check_lock=False)
    directory = (root / output).resolve()
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        typer.echo(f"Servindo {directory} em http://localhost:{port}  (Ctrl+C para parar)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\nAté logo!")


@app.command()
def guard(root: Path = ROOT_OPT, base: str = typer.Option(..., help="Referência da branch principal."),
          head: str = typer.Option(..., help="Referência do pull request."),
          actor: str = typer.Option(..., help="Usuário do GitHub que abriu o PR.")) -> None:
    """Confere se o autor do PR tem permissão para as mudanças (usado no CI)."""
    violations = check_pull_request(root, base, head, actor)
    if violations:
        typer.secho("✗ Mudanças sem permissão:", fg=typer.colors.RED, bold=True)
        for v in violations:
            typer.echo(f"  - {v}")
        raise typer.Exit(1)
    typer.secho("✓ todas as mudanças estão dentro das permissões de @" + actor, fg=typer.colors.GREEN)


@app.command()
def load(package: Path = typer.Argument(..., help="Pasta (ou arquivo) do datapackage.json."),
         database: str = typer.Option(..., "--database", "-d", help="Nome do banco em uai.yml → databases."),
         schema: str = typer.Option("public", help="Schema de destino (PostgreSQL)."),
         only: list[str] = typer.Option([], "--only", help="Carrega só estas tabelas (repetível)."),
         index: list[str] = typer.Option([], "--index", help="Cria índice nestas colunas, quando existirem (repetível)."),
         root: Path = ROOT_OPT) -> None:
    """Carrega um Data Package (CSV e CSV.GZ) no banco — as tabelas são recriadas a cada execução."""
    from .loader import load_package
    project = _project(root)
    try:
        engine = get_engine(project.site, database)
        typer.echo(f"Carregando {package} em '{database}' ({engine.dialect.name})…")
        counts = load_package(engine, package, schema=schema, only=only or None, index=index or None, log=typer.echo)
    except ConfigError as exc:
        _fail(str(exc))
    typer.secho(f"✓ {len(counts)} tabelas, {sum(counts.values()):,} linhas".replace(",", "."), fg=typer.colors.GREEN)


# ----------------------------------------------------------------------------- user
@user_app.command("add")
def user_add(login: str, name: str = typer.Option(..., "--name"), email: str = typer.Option(None),
             github: str = typer.Option(None, help="Usuário no GitHub (necessário para editar via pull request)."),
             password_env: str = typer.Option(None), root: Path = ROOT_OPT) -> None:
    """Cria um usuário. A senha nunca é gravada: só a chave privada cifrada por ela."""
    _load_dotenv(root)
    if not login.replace("_", "").replace("-", "").isalnum() or login != login.lower():
        _fail("Login: use minúsculas, números, '-' e '_'.")
    if login in (_read(_users_file(root)).get("users") or {}):
        _fail(f"O usuário '{login}' já existe. Para trocar a senha: uai user passwd {login}")
    password = _password(password_env)
    _save_user(root, login, _user_entry(name, email, github, crypto.new_user_keys(password, _iterations(root))))
    typer.secho(f"✓ usuário '{login}' criado. Ele ainda não tem acesso a nada: adicione-o a uma organização "
                f"com 'uai org member'.", fg=typer.colors.GREEN)


@user_app.command("passwd")
def user_passwd(login: str, old_password_env: str = typer.Option(None), new_password_env: str = typer.Option(None),
                root: Path = ROOT_OPT) -> None:
    """Troca a senha do próprio usuário (precisa da senha antiga)."""
    users = _read(_users_file(root)).get("users") or {}
    if login not in users:
        _fail(f"Usuário '{login}' não existe.")
    u = users[login]
    old = os.environ[old_password_env] if old_password_env else typer.prompt("Senha atual", hide_input=True)
    new = _password(new_password_env, "Nova senha")
    try:
        keys = crypto.change_password(u["enc_private_key"], u["kdf"]["salt"], u["kdf"]["iter"], old, new, _iterations(root))
    except Exception:  # noqa: BLE001
        _fail("Senha atual incorreta.")
    u.update(public_key=keys.public_key, kdf={"salt": keys.kdf_salt, "iter": keys.kdf_iter},
             enc_private_key=keys.enc_private_key)
    _save_user(root, login, u)
    typer.secho("✓ senha trocada.", fg=typer.colors.GREEN)


@user_app.command("reset")
def user_reset(login: str, password_env: str = typer.Option(None), root: Path = ROOT_OPT) -> None:
    """Redefine a senha de quem esqueceu (administrador). Gera um novo par de chaves; no próximo
    build os painéis são reabertos para ele — nada é perdido."""
    users = _read(_users_file(root)).get("users") or {}
    if login not in users:
        _fail(f"Usuário '{login}' não existe.")
    u = users[login]
    keys = crypto.new_user_keys(_password(password_env, "Nova senha"), _iterations(root))
    u.update(public_key=keys.public_key, kdf={"salt": keys.kdf_salt, "iter": keys.kdf_iter},
             enc_private_key=keys.enc_private_key)
    _save_user(root, login, u)
    typer.secho("✓ senha redefinida. Peça para a pessoa trocá-la com 'uai user passwd'.", fg=typer.colors.GREEN)


@user_app.command("list")
def user_list(root: Path = ROOT_OPT) -> None:
    """Lista usuários e onde cada um atua."""
    project = _project(root)
    for uid, u in project.users.items():
        where = [f"{o}:{'admin' if uid in org.admins else org.members[uid]}"
                 for o, org in project.orgs.items() if uid in org.admins or uid in org.members]
        typer.echo(f"{uid:<14} {u.name:<28} {', '.join(where) or '(sem acesso)'}")


# ----------------------------------------------------------------------------- org
def _org_file(root: Path, org: str) -> Path:
    return root / "access" / f"{org}.yml"


def _need_org(root: Path, org: str) -> dict:
    f = _org_file(root, org)
    if not f.exists():
        _fail(f"A organização '{org}' não existe. Crie com: uai org create {org} --name ... --admin LOGIN")
    return _read(f)


def _need_user(root: Path, login: str) -> None:
    if login not in (_read(_users_file(root)).get("users") or {}):
        _fail(f"O usuário '{login}' não existe. Crie com: uai user add {login} --name ...")


@org_app.command("create")
def org_create(org: str, name: str = typer.Option(..., "--name"), admin: str = typer.Option(..., "--admin"),
               database: list[str] = typer.Option([], "--database", help="Bancos liberados (repetível)."),
               root: Path = ROOT_OPT) -> None:
    """Cria uma organização com um administrador."""
    _need_user(root, admin)
    if _org_file(root, org).exists():
        _fail(f"A organização '{org}' já existe.")
    dump_yaml(_org_file(root, org), {"name": name, "admins": [admin], "profiles": scaffold_profiles(),
                                     "members": {}, "databases": list(database), "allow_sql": False})
    (root / "dashboards" / org).mkdir(parents=True, exist_ok=True)
    _after_access_change(root)
    typer.secho(f"✓ organização '{org}' criada, com {admin} como administrador.", fg=typer.colors.GREEN)


def scaffold_profiles() -> dict:
    from .config import DEFAULT_PROFILES
    return {k: list(v) for k, v in DEFAULT_PROFILES.items()}


@org_app.command("member")
def org_member(org: str, login: str, profile: str = typer.Argument(..., help="viewer, analyst, editor ou um perfil seu."),
               root: Path = ROOT_OPT) -> None:
    """Adiciona alguém à organização (ou muda o perfil dela)."""
    data = _need_org(root, org)
    _need_user(root, login)
    if profile not in data.get("profiles", {}):
        _fail(f"Perfil '{profile}' não existe. Perfis: {', '.join(data.get('profiles', {}))}")
    data.setdefault("members", {})[login] = profile
    dump_yaml(_org_file(root, org), data)
    _after_access_change(root)
    typer.secho(f"✓ {login} agora é '{profile}' em {org}.", fg=typer.colors.GREEN)


@org_app.command("remove")
def org_remove(org: str, login: str, root: Path = ROOT_OPT) -> None:
    """Tira alguém da organização. A chave dos painéis é trocada no próximo build."""
    data = _need_org(root, org)
    if login in data.get("admins", []):
        if len(data["admins"]) == 1:
            _fail("Esta é a única pessoa administradora. Adicione outra antes: uai org admin ORG LOGIN")
        data["admins"].remove(login)
    data.get("members", {}).pop(login, None)
    dump_yaml(_org_file(root, org), data)
    _after_access_change(root)
    typer.secho(f"✓ {login} removido de {org}.", fg=typer.colors.GREEN)


@org_app.command("admin")
def org_admin(org: str, login: str, root: Path = ROOT_OPT) -> None:
    """Torna alguém administrador da organização."""
    data = _need_org(root, org)
    _need_user(root, login)
    if login not in data["admins"]:
        data["admins"].append(login)
    data.get("members", {}).pop(login, None)
    dump_yaml(_org_file(root, org), data)
    _after_access_change(root)
    typer.secho(f"✓ {login} é administrador de {org}.", fg=typer.colors.GREEN)


@org_app.command("profile")
def org_profile(org: str, profile: str, perm: list[str] = typer.Option(..., "--perm", help="view, download, share, create, edit"),
                root: Path = ROOT_OPT) -> None:
    """Cria ou redefine um perfil de permissões."""
    from .config import PERMISSIONS
    bad = [p for p in perm if p not in PERMISSIONS]
    if bad:
        _fail(f"Permissões inválidas: {', '.join(bad)}. Use: {', '.join(PERMISSIONS)}")
    data = _need_org(root, org)
    data.setdefault("profiles", {})[profile] = perm
    dump_yaml(_org_file(root, org), data)
    _after_access_change(root)
    typer.secho(f"✓ perfil '{profile}' de {org}: {', '.join(perm)}", fg=typer.colors.GREEN)


@org_app.command("list")
def org_list(root: Path = ROOT_OPT) -> None:
    """Lista organizações, administradores e perfis."""
    project = _project(root)
    for oid, org in project.orgs.items():
        typer.secho(f"{oid} — {org.name}", bold=True)
        typer.echo(f"  administradores: {', '.join(org.admins)}")
        for p, perms in org.profiles.items():
            who = [u for u, pr in org.members.items() if pr == p]
            typer.echo(f"  {p:<10} [{', '.join(perms)}]  ← {', '.join(who) or '—'}")


# ----------------------------------------------------------------------------- dashboard
@dash_app.command("new")
def dashboard_new(target: str = typer.Argument(..., help="organizacao/nome-do-painel"),
                  title: str = typer.Option(None), database: str = typer.Option(None), root: Path = ROOT_OPT) -> None:
    """Cria o arquivo de um painel novo, com um card de exemplo para você editar."""
    if "/" not in target:
        _fail("Use o formato organizacao/nome-do-painel (ex.: demo/vendas-2026).")
    org, slug = target.split("/", 1)
    data = _need_org(root, org)
    file = root / "dashboards" / org / f"{slug}.yml"
    if file.exists():
        _fail(f"{file} já existe.")
    db = database or (data.get("databases") or ["BANCO"])[0]
    text = (scaffold.NEW_DASHBOARD_YML.replace("__TITLE__", title or slug.replace("-", " ").title())
            .replace("__ORG__", org).replace("__DB__", db).replace("{viz_types}", " | ".join(VIZ_TYPES)))
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    typer.secho(f"✓ criado {file}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
