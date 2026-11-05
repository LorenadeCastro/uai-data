"""Transforma a descrição de um card (YAML) em SQL e no formato que o navegador entende.

O navegador reagrupa os dados quando o leitor usa os filtros do painel. Para isso o SQL agrupa
pelas dimensões do card **mais** as colunas dos filtros, e o navegador soma de volta:

    sum/count -> soma     min/max -> mínimo/máximo     avg -> média ponderada por `<nome>__n`
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, MetaData, Table, and_, func, select, text
from sqlalchemy.sql import ColumnElement

from .config import Card, ConfigError, Dashboard, Measure, Where
from .db import run

_AGG = {"sum": func.sum, "min": func.min, "max": func.max, "avg": func.avg, "count": func.count}


def _where_clause(table: Table, w: Where) -> ColumnElement:
    if w.column not in table.c:
        raise ConfigError(f"'where' usa a coluna '{w.column}', que não existe em {table.name}.")
    col = table.c[w.column]
    op, v = w.op, w.value
    simple = {"=": col == v, "!=": col != v, ">": col > v, ">=": col >= v, "<": col < v, "<=": col <= v}
    if op in simple:
        return simple[op]
    if op == "in":
        return col.in_(v)
    if op == "not_in":
        return col.not_in(v)
    if op == "like":
        return col.like(v)
    if op == "is_null":
        return col.is_(None)
    if op == "not_null":
        return col.is_not(None)
    if op == "between":
        return col.between(v[0], v[1])
    raise ConfigError(f"Operador não suportado: {op}")


def card_filter_columns(card: Card, dash: Dashboard) -> list[str]:
    """Colunas de filtro do painel que este card acompanha (entram no GROUP BY)."""
    if card.filters == "none" or card.source.sql:
        return []
    wanted = [f.column for f in dash.filters]
    if isinstance(card.filters, list):
        wanted = [c for c in wanted if c in card.filters]
    return [c for c in wanted if c not in card.dimensions]


def _measure_expr(table: Table, m: Measure) -> list[ColumnElement]:
    if m.column is not None and m.column not in table.c:
        raise ConfigError(f"A medida '{m.name}' usa a coluna '{m.column}', que não existe em {table.name}.")
    col = table.c[m.column] if m.column else None
    if m.agg == "count":
        expr = func.count(col) if col is not None else func.count()
    elif m.agg == "count_distinct":
        expr = func.count(col.distinct())
    else:
        expr = _AGG[m.agg](col)
    out = [expr.label(m.name)]
    if m.agg == "avg":                      # contagem para a média ponderada no navegador
        out.append(func.count(col).label(f"{m.name}__n"))
    return out


def run_card(engine: Engine, card: Card, dash: Dashboard, *, timeout_s: int, max_rows: int) -> dict[str, Any]:
    """Executa o card e devolve {'columns': [...], 'rows': [...]} pronto para ser cifrado."""
    if card.source.sql:
        columns, rows = run(engine, text(card.source.sql), timeout_s=timeout_s, max_rows=max_rows)
        numeric = {i for i in range(len(columns)) if any(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)}
        meta = []
        for i, name in enumerate(columns):
            is_dim = name in card.sql_dimensions or (not card.sql_dimensions and i not in numeric)
            meta.append({"name": name, "label": name, "kind": "dim" if is_dim else "measure",
                         "agg": None if is_dim else "sum", "format": "text" if is_dim else "number"})
        return {"columns": meta, "rows": rows}

    schema, _, name = card.source.table.rpartition(".")
    table = Table(name, MetaData(), schema=schema or None, autoload_with=engine)

    group_cols = [*card.dimensions, *card_filter_columns(card, dash)]
    for c in group_cols:
        if c not in table.c:
            raise ConfigError(f"A dimensão/filtro '{c}' não existe em {card.source.table}.")

    selected = [table.c[c] for c in group_cols]
    for m in card.measures:
        selected += _measure_expr(table, m)

    stmt = select(*selected)
    if card.where:
        stmt = stmt.where(and_(*[_where_clause(table, w) for w in card.where]))
    if group_cols and card.measures:
        stmt = stmt.group_by(*[table.c[c] for c in group_cols])
    if group_cols:
        stmt = stmt.order_by(*[table.c[c] for c in group_cols])
    if not card.measures:                     # tabela "crua": só as colunas pedidas, com teto de linhas
        stmt = stmt.limit(max_rows + 1)

    columns, rows = run(engine, stmt, timeout_s=timeout_s, max_rows=max_rows)

    meta = [{"name": c, "label": c, "kind": "dim", "agg": None, "format": "text"} for c in group_cols]
    for m in card.measures:
        meta.append({"name": m.name, "label": m.label, "kind": "measure",
                     "agg": "sum" if m.agg == "count" else m.agg, "format": m.format})
        if m.agg == "avg":
            meta.append({"name": f"{m.name}__n", "label": f"{m.name}__n", "kind": "weight",
                         "agg": "sum", "format": "integer"})
    assert [c["name"] for c in meta] == columns, (meta, columns)
    return {"columns": meta, "rows": rows}


def collapse(payload: dict[str, Any], card: Card) -> dict[str, Any]:
    """Reagrupa o resultado do card só pelas dimensões dele, sem as colunas dos filtros.

    É a visão "sem filtros de tela" usada no Excel e no PDF — a mesma conta que o navegador
    faz em data.js quando nenhum filtro está ativo.
    """
    cols = payload["columns"]
    if card.source.sql:
        return payload
    idx = {c["name"]: i for i, c in enumerate(cols)}
    dims = [c for c in cols if c["kind"] == "dim" and c["name"] in card.dimensions]
    measures = [c for c in cols if c["kind"] == "measure"]
    groups: dict[tuple, list] = {}
    for row in payload["rows"]:
        key = tuple(row[idx[d["name"]]] for d in dims)
        acc = groups.setdefault(key, [[0.0, 0.0, None, None, False] for _ in measures])
        for k, m in enumerate(measures):
            v = row[idx[m["name"]]]
            if v is None:
                continue
            a = acc[k]
            a[4] = True
            if m["agg"] == "avg":
                w = row[idx[f"{m['name']}__n"]] if f"{m['name']}__n" in idx else 1
                a[0] += v * w
                a[1] += w
            elif m["agg"] == "min":
                a[2] = v if a[2] is None else min(a[2], v)
            elif m["agg"] == "max":
                a[3] = v if a[3] is None else max(a[3], v)
            else:
                a[0] += v
    def value(m: dict, a: list):
        if not a[4]:
            return None
        return {"avg": (a[0] / a[1] if a[1] else None), "min": a[2], "max": a[3]}.get(m["agg"], a[0])
    rows = [[*key, *[value(m, a) for m, a in zip(measures, acc)]] for key, acc in groups.items()]

    def order(v):
        return (v is not None, str(v).zfill(12) if isinstance(v, str) and v.isdigit() else str(v) if v is not None else "")
    n = len(dims)
    rows.sort(key=lambda r: tuple(order(x) for x in r[:n]))
    for s_ in reversed(card.sort):
        names = [c["name"] for c in [*dims, *measures]]
        if s_.by in names:
            i = names.index(s_.by)
            rows.sort(key=lambda r, i=i: (r[i] is not None, r[i] if r[i] is not None else 0), reverse=s_.dir == "desc")
    if card.top:
        rows = rows[: card.top]
    return {"columns": [*dims, *measures], "rows": rows}
