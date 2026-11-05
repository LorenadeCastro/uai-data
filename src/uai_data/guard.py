"""Guarda de permissões de edição, executado no CI a cada pull request.

Sem servidor, "quem pode editar" é "quem pode mudar arquivos no repositório". O guard compara o
pull request com a branch principal e confere, arquivo por arquivo, se o autor tem a permissão
que a mudança exige — usando SEMPRE as regras da branch principal (nunca as do PR).

    painel novo ..................... permissão 'create' na organização
    painel alterado/removido ........ permissão 'edit'
    permissões de um painel ......... administrador da organização
    access/<org>.yml ................ administrador da organização (criar org: administrador do site)
    access/users.yml ................ o próprio usuário (ou um administrador)
    access.lock.json ................ administrador do site (o workflow de publicação o atualiza sozinho)
    qualquer outro arquivo .......... administrador do site

Combine com "Require status checks" + proteção de branch no GitHub (veja SECURITY.md).
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

import yaml

from . import access
from .config import ConfigError, Project


def _git(root: Path, *args: str, text: bool = True):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=text).stdout


def _extract(root: Path, rev: str, dest: Path) -> Path:
    data = _git(root, "archive", "--format=tar", rev, text=False)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def _yaml_at(root: Path, rev: str, path: str) -> dict | None:
    try:
        raw = _git(root, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None
    try:
        return yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}


def check_pull_request(root: str | Path, base: str, head: str, actor: str) -> list[str]:
    """Devolve a lista de violações (vazia = tudo certo)."""
    root = Path(root)
    violations: list[str] = []
    changes = [line.split("\t") for line in _git(root, "diff", "--name-status", "--no-renames", f"{base}...{head}").splitlines()]

    with tempfile.TemporaryDirectory() as tmp:
        base_dir = _extract(root, base, Path(tmp) / "base")
        try:
            trusted = Project.load(base_dir)
        except ConfigError as exc:
            return [f"A branch principal está com configuração inválida; corrija-a antes. {exc}"]

        who = access.user_for_github(trusted, actor)
        site_admin = access.can_manage_site(trusted, who)

        def org_admin(org_id: str) -> bool:
            org = trusted.orgs.get(org_id)
            return bool(org and who and access.is_admin(org, who)) or site_admin

        def any_admin() -> bool:
            return site_admin or any(who in o.admins for o in trusted.orgs.values())

        for status, path in changes:
            parts = Path(path).parts
            label = {"A": "novo", "M": "alterado", "D": "removido"}.get(status, status)
            where = f"{path} [{label}]"

            if len(parts) == 3 and parts[0] == "dashboards" and path.endswith(".yml"):
                org_id = parts[1]
                org = trusted.orgs.get(org_id)
                if org is None:
                    violations.append(f"{where}: a organização '{org_id}' não existe.")
                    continue
                new = _yaml_at(root, head, path) or {}
                old = _yaml_at(root, base, path) or {}
                perm = "create" if status == "A" else "edit"
                allowed = site_admin or (who and (
                    perm in access.org_perms(org, who)
                    or (status != "A" and perm in _dash_perms(trusted, org_id, parts[2][:-4], who))
                ))
                if not allowed:
                    violations.append(f"{where}: @{actor} não tem a permissão '{perm}' em '{org_id}'.")
                if new and new.get("organization") != org_id and status != "D":
                    violations.append(f"{where}: 'organization' precisa ser '{org_id}'.")
                perms_changed = (new.get("access"), new.get("share_epoch", 0)) != (old.get("access"), old.get("share_epoch", 0))
                if status != "D" and perms_changed and (status == "M" or new.get("access")) and not org_admin(org_id):
                    violations.append(f"{where}: só o administrador de '{org_id}' altera 'access' e 'share_epoch'.")

            elif len(parts) == 2 and parts[0] == "access" and parts[1] == "users.yml":
                old_u = (_yaml_at(root, base, path) or {}).get("users") or {}
                new_u = (_yaml_at(root, head, path) or {}).get("users") or {}
                for uid in sorted(set(old_u) | set(new_u)):
                    if old_u.get(uid) == new_u.get(uid):
                        continue
                    own = (old_u.get(uid) or new_u.get(uid) or {}).get("github", "").lower() == actor.lower()
                    if uid not in new_u:
                        own = False                       # remover usuário é decisão de admin
                    if not (own or any_admin()):
                        violations.append(f"{path}: @{actor} não pode alterar o usuário '{uid}'.")

            elif len(parts) == 2 and parts[0] == "access" and path.endswith(".yml"):
                org_id = parts[1][:-4]
                ok = site_admin if status in ("A", "D") else org_admin(org_id)
                if not ok:
                    quem = "o administrador do site" if status in ("A", "D") else f"um administrador de '{org_id}'"
                    violations.append(f"{where}: só {quem} pode fazer isso.")

            # access.lock.json é gravado pelo workflow de publicação; num PR só o administrador do site mexe
            # (senão alguém poderia desfazer a troca de chave de uma revogação).

            elif not site_admin:
                violations.append(f"{where}: só administradores do site alteram este arquivo.")

        head_dir = _extract(root, head, Path(tmp) / "head")
        try:
            Project.load(head_dir)
        except ConfigError as exc:
            violations.append(f"A configuração do PR é inválida:\n{exc}")

    return violations


def _dash_perms(project: Project, org_id: str, slug: str, user: str) -> frozenset[str]:
    dash = project.dashboards.get(f"{org_id}/{slug}")
    return access.dashboard_perms(project.orgs[org_id], dash, user) if dash else frozenset()
