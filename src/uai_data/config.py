"""Modelos de configuração do Uai Data.

Tudo que o usuário escreve (uai.yml, access/*.yml, dashboards/*/*.yml) é validado aqui,
com mensagens de erro que dizem qual arquivo e qual campo estão errados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PERMISSIONS = ("view", "download", "share", "create", "edit")
Perm = Literal["view", "download", "share", "create", "edit"]

DEFAULT_PROFILES: dict[str, list[str]] = {
    "viewer": ["view"],
    "analyst": ["view", "download", "share"],
    "editor": ["view", "download", "share", "create", "edit"],
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

VIZ_TYPES = (
    "table", "pivot", "number", "gauge", "bar", "hbar", "stacked_bar", "line", "area",
    "scatter", "pie", "donut", "heatmap", "funnel", "treemap", "waterfall",
)
AGGS = ("sum", "count", "avg", "min", "max", "count_distinct")


class ConfigError(Exception):
    """Erro de configuração com mensagem pensada para quem não é programador."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- site
class Database(_Model):
    dsn_env: str = Field(description="Nome da variável de ambiente (secret) com a URL do banco.")
    statement_timeout_s: int = 120


class SiteConfig(_Model):
    name: str = "Uai Data"
    tagline: str = "Explore. Analise. Descubra."
    repo: str | None = Field(default=None, description="owner/repo — usado nos links de edição.")
    branch: str = "main"
    locale: str = "pt-BR"
    currency: str = "BRL"
    csv_sep: str = ";"
    csv_decimal: str = ","
    site_salt: str
    site_admins: list[str] = []
    databases: dict[str, Database] = {}
    catalog_schemas: list[str] = ["public"]
    pbkdf2_iterations: int = 600_000
    max_rows_per_card: int = 50_000


# --------------------------------------------------------------------------- pessoas
class KDF(_Model):
    salt: str
    iter: int


class User(_Model):
    name: str
    email: str | None = None
    github: str | None = None
    public_key: str
    kdf: KDF
    enc_private_key: str


class Organization(_Model):
    name: str
    admins: list[str]
    profiles: dict[str, list[Perm]] = Field(default_factory=lambda: dict(DEFAULT_PROFILES))
    members: dict[str, str] = {}
    databases: list[str] = []
    allow_sql: bool = False

    @field_validator("admins")
    @classmethod
    def _need_admin(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("toda organização precisa de pelo menos um administrador")
        return v

    @model_validator(mode="after")
    def _members_have_profile(self) -> Organization:
        for user, profile in self.members.items():
            if profile not in self.profiles:
                raise ValueError(
                    f"membro '{user}' usa o perfil '{profile}', que não existe em 'profiles' "
                    f"({', '.join(self.profiles)})"
                )
        return self


# --------------------------------------------------------------------------- painéis
class Measure(_Model):
    column: str | None = None  # None só vale para count(*)
    agg: Literal["sum", "count", "avg", "min", "max", "count_distinct"] = "sum"
    name: str | None = None
    label: str | None = None
    format: Literal["currency", "number", "integer", "percent", "text"] = "number"

    @model_validator(mode="after")
    def _check(self) -> Measure:
        if self.column is None and self.agg != "count":
            raise ValueError("measures sem 'column' só podem usar agg: count")
        if self.column is not None and not IDENT_RE.match(self.column):
            raise ValueError(f"nome de coluna inválido: {self.column!r}")
        if self.name is None:
            self.name = f"{self.agg}_{self.column or 'rows'}"
        if self.label is None:
            self.label = self.name
        return self


class Where(_Model):
    column: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "in", "not_in", "like", "is_null", "not_null", "between"] = "="
    value: Any = None

    @field_validator("column")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT_RE.match(v):
            raise ValueError(f"nome de coluna inválido: {v!r}")
        return v


class Source(_Model):
    table: str | None = Field(default=None, description="schema.tabela ou tabela")
    sql: str | None = Field(default=None, description="Consulta nativa (somente leitura).")

    @model_validator(mode="after")
    def _one(self) -> Source:
        if bool(self.table) == bool(self.sql):
            raise ValueError("informe exatamente um entre 'table' e 'sql'")
        if self.table and not all(IDENT_RE.match(p) for p in self.table.split(".")):
            raise ValueError(f"nome de tabela inválido: {self.table!r}")
        return self


class SortSpec(_Model):
    by: str
    dir: Literal["asc", "desc"] = "desc"


class Card(_Model):
    id: str
    title: str
    viz: Literal[
        "table", "pivot", "number", "gauge", "bar", "hbar", "stacked_bar", "line", "area",
        "scatter", "pie", "donut", "heatmap", "funnel", "treemap", "waterfall",
    ] = "table"
    description: str | None = None
    source: Source
    dimensions: list[str] = []
    measures: list[Measure] = []
    where: list[Where] = []
    # como desenhar
    x: str | None = None
    series: str | None = None
    y: list[str] = []
    rows: list[str] = []          # pivot
    columns: list[str] = []       # pivot
    sort: list[SortSpec] = []
    top: int | None = None
    max_value: float | None = None  # gauge
    width: int = Field(default=6, ge=1, le=12)
    height: int = Field(default=340, ge=120, le=1200)
    filters: Literal["all", "none"] | list[str] = "all"
    # colunas de uma consulta nativa
    sql_dimensions: list[str] = []

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("id do card: use letras minúsculas, números, '-' ou '_'")
        return v

    @field_validator("dimensions", "sql_dimensions")
    @classmethod
    def _dims(cls, v: list[str]) -> list[str]:
        for d in v:
            if not IDENT_RE.match(d):
                raise ValueError(f"nome de coluna inválido: {d!r}")
        return v


class FilterSpec(_Model):
    column: str
    label: str | None = None
    type: Literal["select", "text"] = "select"


class DashboardAccess(_Model):
    private: bool = False
    # chave começa com '@' => perfil (ex.: '@viewer'); caso contrário, login do usuário
    grants: dict[str, list[Perm]] = {}


class Dashboard(_Model):
    title: str
    organization: str
    description: str | None = None
    database: str | None = None
    filters: list[FilterSpec] = []
    cards: list[Card]
    access: DashboardAccess = DashboardAccess()
    share_epoch: int = 0   # aumente para invalidar os links de compartilhamento
    tags: list[str] = []

    @model_validator(mode="after")
    def _unique_cards(self) -> Dashboard:
        ids = [c.id for c in self.cards]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"ids de card repetidos: {', '.join(sorted(dup))}")
        return self


# --------------------------------------------------------------------------- projeto
class Project:
    """Tudo que está no repositório: site, usuários, organizações e painéis."""

    def __init__(self, root: Path, site: SiteConfig, users: dict[str, User],
                 orgs: dict[str, Organization], dashboards: dict[str, Dashboard]):
        self.root = root
        self.site = site
        self.users = users
        self.orgs = orgs
        self.dashboards = dashboards  # chave: 'org/slug'

    # ---- carregamento
    @classmethod
    def load(cls, root: str | Path = ".") -> Project:
        root = Path(root).resolve()
        site = _load(root / "uai.yml", SiteConfig)
        users_file = root / "access" / "users.yml"
        raw_users = _read_yaml(users_file).get("users", {}) if users_file.exists() else {}
        users = {k: _validate(User, v, users_file, f"users.{k}") for k, v in (raw_users or {}).items()}

        orgs: dict[str, Organization] = {}
        for f in sorted((root / "access").glob("*.yml")) if (root / "access").exists() else []:
            if f.name == "users.yml":
                continue
            org_id = f.stem
            _check_slug(org_id, f)
            orgs[org_id] = _load(f, Organization)

        dashboards: dict[str, Dashboard] = {}
        for f in sorted((root / "dashboards").glob("*/*.yml")) if (root / "dashboards").exists() else []:
            org_id, slug = f.parent.name, f.stem
            _check_slug(slug, f)
            dash = _load(f, Dashboard)
            if dash.organization != org_id:
                raise ConfigError(
                    f"{f.relative_to(root)}: 'organization: {dash.organization}' não bate com a "
                    f"pasta '{org_id}'. Painéis de uma organização ficam em dashboards/{org_id}/."
                )
            dashboards[f"{org_id}/{slug}"] = dash

        project = cls(root, site, users, orgs, dashboards)
        project.validate()
        return project

    def validate(self) -> None:
        problems: list[str] = []
        for org_id, org in self.orgs.items():
            for u in [*org.admins, *org.members]:
                if u not in self.users:
                    problems.append(f"access/{org_id}.yml: usuário '{u}' não existe em access/users.yml")
            for db in org.databases:
                if db not in self.site.databases:
                    problems.append(f"access/{org_id}.yml: banco '{db}' não existe em uai.yml → databases")
        for u in self.site.site_admins:
            if u not in self.users:
                problems.append(f"uai.yml: site_admins contém '{u}', que não existe em access/users.yml")
        for key, dash in self.dashboards.items():
            org = self.orgs.get(dash.organization)
            if org is None:
                problems.append(f"dashboards/{key}.yml: a organização '{dash.organization}' não existe")
                continue
            if dash.database and dash.database not in org.databases:
                problems.append(
                    f"dashboards/{key}.yml: a organização '{dash.organization}' não tem permissão de usar "
                    f"o banco '{dash.database}' (veja 'databases' em access/{dash.organization}.yml)"
                )
            for card in dash.cards:
                if card.source.sql and not org.allow_sql:
                    problems.append(
                        f"dashboards/{key}.yml: o card '{card.id}' usa 'sql', mas a organização "
                        f"'{dash.organization}' não tem 'allow_sql: true'"
                    )
                if not dash.database:
                    problems.append(f"dashboards/{key}.yml: defina 'database' (nome em uai.yml → databases)")
                elif dash.database not in self.site.databases:
                    problems.append(f"dashboards/{key}.yml: banco '{dash.database}' não existe em uai.yml → databases")
                problems += _check_card(key, card)
            for who in dash.access.grants:
                if who.startswith("@"):
                    if who[1:] not in org.profiles:
                        problems.append(f"dashboards/{key}.yml: perfil '{who}' não existe na organização")
                elif who not in self.users:
                    problems.append(f"dashboards/{key}.yml: usuário '{who}' não existe")
        if problems:
            raise ConfigError("Problemas encontrados:\n  - " + "\n  - ".join(problems))


def _check_card(key: str, card: Card) -> list[str]:
    out: list[str] = []
    where = f"dashboards/{key}.yml: card '{card.id}'"
    if card.source.table and not card.measures and card.viz not in ("table",):
        out.append(f"{where}: '{card.viz}' precisa de pelo menos uma medida (measures)")
    if card.source.table and not card.dimensions and not card.measures:
        out.append(f"{where}: informe 'dimensions' (colunas) e/ou 'measures'")
    names = [m.name for m in card.measures]
    if len(set(names)) != len(names):
        out.append(f"{where}: medidas com o mesmo 'name' — defina 'name' diferente em cada uma")
    known = {*card.dimensions, *card.sql_dimensions, *names}
    for ref_name, ref in (("x", card.x), ("series", card.series)):
        if ref and card.source.table and ref not in card.dimensions:
            out.append(f"{where}: '{ref_name}: {ref}' precisa estar em 'dimensions'")
    for y in card.y:
        if card.source.table and y not in names:
            out.append(f"{where}: 'y' contém '{y}', que não é o 'name' de nenhuma medida")
    for s in card.sort:
        if card.source.table and s.by not in known:
            out.append(f"{where}: 'sort.by: {s.by}' não é dimensão nem medida")
    if card.filters != "none" and any(m.agg == "count_distinct" for m in card.measures):
        out.append(
            f"{where}: 'count_distinct' não pode ser recalculado quando o leitor usa filtros do painel. "
            f"Use 'filters: none' neste card ou troque a medida."
        )
    return out


# --------------------------------------------------------------------------- utilidades
def _check_slug(value: str, f: Path) -> None:
    if not SLUG_RE.match(value):
        raise ConfigError(f"{f}: nome de arquivo/pasta '{value}' inválido — use minúsculas, números, '-' e '_'")


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML inválido — {exc}") from exc
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: arquivo não encontrado. Rode 'uai init' para criar um projeto.") from exc
    return data or {}


def _validate(model, data, path: Path, where: str = ""):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"  - {where + '.' if where else ''}{loc}: {err['msg']}")
        raise ConfigError(f"{path}:\n" + "\n".join(lines)) from exc


def _load(path: Path, model):
    return _validate(model, _read_yaml(path), path)


def dump_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
