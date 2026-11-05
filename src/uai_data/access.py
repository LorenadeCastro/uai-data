"""Regras de permissão: quem pode ver, baixar, compartilhar, criar e editar.

O administrador de cada organização define (em access/<org>.yml) os perfis e quem usa cada perfil.
Um painel pode dar permissões extras ou ser 'private' (só quem foi listado, além dos admins).
"""

from __future__ import annotations

from .config import PERMISSIONS, Dashboard, Organization, Project

ALL = frozenset(PERMISSIONS)


def is_admin(org: Organization, user: str) -> bool:
    return user in org.admins


def org_perms(org: Organization, user: str) -> frozenset[str]:
    """Permissões do usuário na organização, sem olhar painel nenhum."""
    if is_admin(org, user):
        return ALL
    profile = org.members.get(user)
    return frozenset(org.profiles[profile]) if profile else frozenset()


def dashboard_perms(org: Organization, dash: Dashboard, user: str) -> frozenset[str]:
    """Permissões efetivas do usuário em um painel específico."""
    if is_admin(org, user):
        return ALL
    if user not in org.members:
        return frozenset()
    base = frozenset() if dash.access.private else org_perms(org, user)
    extra: set[str] = set()
    profile = org.members[user]
    for who, perms in dash.access.grants.items():
        if who == f"@{profile}" or who == user:
            extra.update(perms)
    return base | extra


def viewers(project: Project, dash_key: str) -> list[str]:
    """Todos os usuários que enxergam o painel, em ordem alfabética."""
    dash = project.dashboards[dash_key]
    org = project.orgs[dash.organization]
    candidates = {*org.admins, *org.members}
    return sorted(u for u in candidates if "view" in dashboard_perms(org, dash, u))


def downloaders(project: Project, dash_key: str) -> list[str]:
    """Quem pode baixar (xlsx/pdf) o painel: precisa ver e ter a permissão 'download'."""
    dash = project.dashboards[dash_key]
    org = project.orgs[dash.organization]
    return sorted(u for u in viewers(project, dash_key) if "download" in dashboard_perms(org, dash, u))


def users_with(project: Project, org_id: str, perm: str) -> list[str]:
    """Usuários da organização com uma permissão em nível de organização (ex.: 'create')."""
    org = project.orgs[org_id]
    return sorted(u for u in {*org.admins, *org.members} if perm in org_perms(org, u))


def can_manage_site(project: Project, user: str | None) -> bool:
    return bool(user) and user in project.site.site_admins


def user_for_github(project: Project, github: str) -> str | None:
    for uid, user in project.users.items():
        if user.github and user.github.lower() == github.lower():
            return uid
    return None
