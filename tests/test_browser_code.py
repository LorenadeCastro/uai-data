import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from conftest import PW

from uai_data.builder import build
from uai_data.config import Project

NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="Node.js não encontrado")
def test_javascript_opens_python_site_and_matches_sql(project, tmp_path):
    site = tmp_path / "site"
    build(Project.load(project), site)
    out = subprocess.run([NODE, str(Path(__file__).parent / "node_check.mjs"), str(site), "bia", PW["bia"], "por-regiao"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["title"] == "Vendas — visão geral"
    con = sqlite3.connect(project / "demo" / "vendas.db")
    for key, sql in (("all", "select regiao, sum(valor) from vendas group by 1"),
                     ("y2025", "select regiao, sum(valor) from vendas where ano=2025 group by 1")):
        truth = dict(con.execute(sql).fetchall())
        rows = {r[0]: r[1] for r in got[key]["rows"]}
        assert rows.keys() == truth.keys()
        for k, v in truth.items():
            assert rows[k] == pytest.approx(v, rel=1e-9)
