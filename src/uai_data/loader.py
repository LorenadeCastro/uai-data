"""Carrega um Data Package (datapackage.json + CSVs, inclusive .csv.gz) em um banco.

No PostgreSQL usa COPY (rápido: ~1 milhão de linhas em segundos). No SQLite (testes) usa INSERT.
É o caminho para o caso "o servidor de dados publica CSVs no GitHub": o workflow baixa o
repositório, roda `uai load` e depois `uai build`.
"""

from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from sqlalchemy import Engine, text

from .config import IDENT_RE, ConfigError

PG_TYPES = {
    "string": "TEXT", "number": "NUMERIC", "integer": "BIGINT", "boolean": "BOOLEAN",
    "datetime": "TIMESTAMP", "date": "DATE", "time": "TIME", "year": "INTEGER", "any": "TEXT",
}
SQLITE_TYPES = {
    "string": "TEXT", "number": "NUMERIC", "integer": "INTEGER", "boolean": "INTEGER",
    "datetime": "TEXT", "date": "TEXT", "time": "TEXT", "year": "INTEGER", "any": "TEXT",
}


def _quote(name: str) -> str:
    if not IDENT_RE.match(name):
        raise ConfigError(f"Nome de tabela/coluna inválido para o banco: {name!r}")
    return f'"{name}"'


def read_package(path: str | Path) -> tuple[Path, list[dict]]:
    path = Path(path)
    descriptor = path / "datapackage.json" if path.is_dir() else path
    if not descriptor.exists():
        raise ConfigError(f"Não encontrei {descriptor}. Aponte para a pasta (ou o arquivo) do datapackage.json.")
    pkg = json.loads(descriptor.read_text(encoding="utf-8"))
    resources = [r for r in pkg.get("resources", []) if r.get("path") and r.get("schema")]
    if not resources:
        raise ConfigError(f"{descriptor} não tem recursos com 'path' e 'schema'.")
    return descriptor.parent, resources


def _open(path: Path, mode: str = "rb"):
    return gzip.open(path, mode) if path.suffix == ".gz" else open(path, mode)


def ddl(resource: dict, schema: str | None, sqlite: bool) -> str:
    types = SQLITE_TYPES if sqlite else PG_TYPES
    cols = ",\n  ".join(
        f"{_quote(f['name'])} {types.get(f.get('type', 'string'), 'TEXT')}" for f in resource["schema"]["fields"]
    )
    full = f"{_quote(schema)}." if schema and not sqlite else ""
    return f"CREATE TABLE {full}{_quote(resource['name'])} (\n  {cols}\n)"


def load_package(engine: Engine, package: str | Path, *, schema: str | None = "public", only: list[str] | None = None,
                 index: list[str] | None = None, log: Callable[[str], None] = print) -> dict[str, int]:
    """Recria cada tabela do pacote e carrega os dados. Devolve {tabela: linhas}."""
    base, resources = read_package(package)
    if only:
        wanted = set(only)
        missing = wanted - {r["name"] for r in resources}
        if missing:
            raise ConfigError(f"Tabelas que não estão no pacote: {', '.join(sorted(missing))}")
        resources = [r for r in resources if r["name"] in wanted]
    sqlite = engine.dialect.name == "sqlite"
    counts: dict[str, int] = {}
    for res in resources:
        file = base / res["path"]
        if not file.exists():
            raise ConfigError(f"Arquivo de dados não encontrado: {file}")
        name = res["name"]
        qualified = f"{_quote(schema)}.{_quote(name)}" if schema and not sqlite else _quote(name)
        with engine.begin() as conn:
            if schema and not sqlite:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote(schema)}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {qualified}"))
            conn.execute(text(ddl(res, schema, sqlite)))
        n = _copy_sqlite(engine, res, file, qualified) if sqlite else _copy_postgres(engine, res, file, qualified)
        with engine.begin() as conn:
            for col in index or []:
                if any(f["name"] == col for f in res["schema"]["fields"]):
                    conn.execute(text(f"CREATE INDEX ON {qualified} ({_quote(col)})"))
        if not sqlite:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f"ANALYZE {qualified}"))
        counts[name] = n
        log(f"  ✓ {name}: {n:,} linhas".replace(",", "."))
    return counts


def _header(file: Path, resource: dict) -> list[str]:
    with _open(file, "rt") as fh:
        header = next(csv.reader(fh))
    declared = [f["name"] for f in resource["schema"]["fields"]]
    unknown = [h for h in header if h not in declared]
    if unknown:
        raise ConfigError(f"{file.name}: colunas no CSV que não estão no schema: {', '.join(unknown)}")
    return header


def _copy_postgres(engine: Engine, resource: dict, file: Path, qualified: str) -> int:
    header = _header(file, resource)
    cols = ", ".join(_quote(c) for c in header)
    sql = f"COPY {qualified} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    raw = engine.raw_connection()
    try:
        conn = raw.driver_connection
        with conn.cursor() as cur:
            with cur.copy(sql) as copy, _open(file) as fh:
                while chunk := fh.read(1 << 20):
                    copy.write(chunk)
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        raw.close()


def _convert(kind: str) -> Callable[[str], object]:
    def num(v: str):
        return float(v)
    def boolean(v: str):
        return 1 if v.strip().lower() in ("true", "t", "1", "yes", "sim") else 0
    return {"number": num, "integer": lambda v: int(float(v)), "boolean": boolean}.get(kind, lambda v: v)


def _rows(file: Path, header: list[str], convert: list[Callable]) -> Iterator[list]:
    with _open(file, "rt") as fh:
        reader = csv.reader(fh)
        next(reader)
        for row in reader:
            yield [None if v == "" else conv(v) for v, conv in zip(row, convert)]


def _copy_sqlite(engine: Engine, resource: dict, file: Path, qualified: str) -> int:
    header = _header(file, resource)
    kinds = {f["name"]: f.get("type", "string") for f in resource["schema"]["fields"]}
    convert = [_convert(kinds[h]) for h in header]
    cols = ", ".join(_quote(c) for c in header)
    marks = ", ".join("?" for _ in header)
    raw = engine.raw_connection()
    try:
        con: sqlite3.Connection = raw.driver_connection
        batch, n = [], 0
        for row in _rows(file, header, convert):
            batch.append(row)
            if len(batch) >= 20_000:
                con.executemany(f"INSERT INTO {qualified} ({cols}) VALUES ({marks})", batch)
                n += len(batch); batch = []
        if batch:
            con.executemany(f"INSERT INTO {qualified} ({cols}) VALUES ({marks})", batch)
            n += len(batch)
        con.commit()
        return n
    finally:
        raw.close()
