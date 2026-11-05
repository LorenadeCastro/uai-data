import csv
import gzip
import json
import os

import pytest
from sqlalchemy import create_engine, text

from uai_data.loader import load_package


def make_package(tmp_path):
    with gzip.open(tmp_path / "t.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ano", "uo", "valor", "ativo", "dt"])
        w.writerow([2026, "SEPLAG", "10.50", "true", "2026/01/05 10:00:00"])
        w.writerow([2026, "SEE", "", "false", "2026/02/01 00:00:00"])
        w.writerow([2026, "FES", "1234567.89", "true", ""])
    fields = [{"name": "ano", "type": "integer"}, {"name": "uo", "type": "string"}, {"name": "valor", "type": "number"},
              {"name": "ativo", "type": "boolean"}, {"name": "dt", "type": "datetime"}]
    (tmp_path / "datapackage.json").write_text(json.dumps({"resources": [{"name": "t", "path": "t.csv.gz", "schema": {"fields": fields}}]}))
    return tmp_path


def test_load_sqlite(tmp_path):
    pkg = make_package(tmp_path)
    eng = create_engine(f"sqlite:///{tmp_path}/x.db")
    assert load_package(eng, pkg, log=lambda *_: None) == {"t": 3}
    with eng.connect() as c:
        assert c.execute(text("select sum(valor), count(valor) from t")).one() == (1234578.39, 2)


@pytest.mark.skipif(not os.environ.get("UAI_TEST_PG"), reason="defina UAI_TEST_PG=postgresql://... para testar o COPY")
def test_load_postgres(tmp_path):
    from uai_data.db import normalize_dsn
    pkg = make_package(tmp_path)
    eng = create_engine(normalize_dsn(os.environ["UAI_TEST_PG"]))
    load_package(eng, pkg, schema="uai_test", log=lambda *_: None)
    with eng.connect() as c:
        assert str(c.execute(text("select sum(valor) from uai_test.t")).scalar()) == "1234578.39"
        assert c.execute(text("select count(*) from uai_test.t where dt is null")).scalar() == 1
        c.execute(text("drop schema uai_test cascade")); c.commit()
