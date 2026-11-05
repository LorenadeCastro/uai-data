"""Conexão com o banco (PostgreSQL) e execução de consultas somente leitura."""

from __future__ import annotations

import datetime as dt
import decimal
import os
import uuid
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import Connection

from .config import ConfigError, SiteConfig


def normalize_dsn(dsn: str) -> str:
    """Aceita as URLs que o dia a dia produz (postgres://, postgresql://) e usa o driver psycopg 3."""
    for old in ("postgres://", "postgresql://"):
        if dsn.startswith(old):
            return "postgresql+psycopg://" + dsn[len(old):]
    return dsn


def get_engine(site: SiteConfig, name: str) -> Engine:
    cfg = site.databases.get(name)
    if cfg is None:
        raise ConfigError(f"Banco '{name}' não está em uai.yml → databases.")
    dsn = os.environ.get(cfg.dsn_env)
    if not dsn:
        raise ConfigError(
            f"A variável de ambiente {cfg.dsn_env} não está definida (banco '{name}'). "
            f"Localmente: export {cfg.dsn_env}='postgresql://usuario:senha@host:5432/banco'. "
            f"No GitHub: Settings → Secrets and variables → Actions → New repository secret."
        )
    return create_engine(normalize_dsn(dsn), pool_pre_ping=True)


def json_safe(value: Any) -> Any:
    """Converte tipos do banco para algo que cabe em JSON, sem perder os centavos."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def read_only(conn: Connection, timeout_s: int) -> None:
    """Garante que nada escreve no banco, mesmo que a consulta nativa tente."""
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_s) * 1000}"))


def run(engine: Engine, statement, params: dict | None = None, timeout_s: int = 120,
        max_rows: int = 50_000) -> tuple[list[str], list[list[Any]]]:
    with engine.connect() as conn:
        read_only(conn, timeout_s)
        result = conn.execute(statement, params or {})
        columns = list(result.keys())
        rows = result.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise ConfigError(
                f"A consulta devolveu mais de {max_rows} linhas. Reduza as dimensões do card, "
                f"use 'top' ou 'where' — ou aumente 'max_rows_per_card' em uai.yml."
            )
        return columns, [[json_safe(v) for v in row] for row in rows]


def describe_catalog(engine: Engine, schemas: list[str]) -> list[dict]:
    """Tabelas e colunas (sem dados) para a página 'Explorar dados' de quem pode criar painéis."""
    insp = inspect(engine)
    out = []
    for schema in schemas:
        schema_arg = schema if engine.dialect.name != "sqlite" else None
        for table in sorted(insp.get_table_names(schema=schema_arg)):
            cols = [{"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(table, schema=schema_arg)]
            out.append({"schema": schema, "table": table, "columns": cols})
    return out
