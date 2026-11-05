import sqlite3

import pytest

from uai_data.config import ConfigError, Project
from uai_data.db import get_engine
from uai_data.queries import collapse, run_card


def test_config_errors_are_readable(project):
    f = project / "dashboards" / "demo" / "vendas.yml"
    f.write_text(f.read_text().replace("database: demo", "database: inexistente", 1))
    with pytest.raises(ConfigError, match="inexistente"):
        Project.load(project)


def test_sql_cards_need_permission(project):
    f = project / "dashboards" / "demo" / "nativo.yml"
    f.write_text("title: x\norganization: demo\ndatabase: demo\ncards:\n  - {id: a, title: a, source: {sql: 'select 1 as n'}}\n")
    with pytest.raises(ConfigError, match="allow_sql"):
        Project.load(project)


def test_unknown_field_is_rejected(project):
    f = project / "dashboards" / "demo" / "vendas.yml"
    f.write_text(f.read_text().replace("title: Vendas", "titulo_errado: x\ntitle: Vendas", 1))
    with pytest.raises(ConfigError, match="titulo_errado"):
        Project.load(project)


def test_collapse_matches_sql(project):
    p = Project.load(project)
    dash = p.dashboards["demo/vendas"]
    engine = get_engine(p.site, "demo")
    con = sqlite3.connect(project / "demo" / "vendas.db")
    for card in dash.cards:
        raw = run_card(engine, card, dash, timeout_s=60, max_rows=50_000)
        flat = collapse(raw, card)
        if card.id == "detalhe":
            truth = {r[:3]: r[3:] for r in con.execute("select regiao, produto, vendedor, sum(valor), sum(quantidade), avg(valor) from vendas group by 1,2,3")}
            got = {tuple(r[:3]): r[3:] for r in flat["rows"]}
            assert got.keys() == truth.keys()
            for k, v in truth.items():
                assert got[k] == pytest.approx(v, rel=1e-9)
        if card.id == "faturamento":
            assert flat["rows"][0][0] == pytest.approx(con.execute("select sum(valor) from vendas").fetchone()[0])
        if card.id == "top-vendedores":
            assert len(flat["rows"]) == 10 and flat["rows"][0][1] >= flat["rows"][-1][1]
