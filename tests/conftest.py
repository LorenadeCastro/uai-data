import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from uai_data.cli import app

runner = CliRunner()
PW = {"lorena": "senha-admin-123456", "ana": "senha-ana-1234567", "caio": "senha-caio-123456", "bia": "senha-bia-1234567"}
ENV = {f"PW_{k.upper()}": v for k, v in PW.items()}


def cli(*args, root: Path | None = None):
    full = [*args, *(["--root", str(root)] if root else [])]
    result = runner.invoke(app, full, env=ENV)
    assert result.exit_code == 0, result.output
    return result


@pytest.fixture(scope="session")
def base_project(tmp_path_factory) -> Path:
    """Projeto de demonstração com 1 administrador e 3 pessoas (editor, analista, leitora)."""
    root = tmp_path_factory.mktemp("base") / "p"
    cli("init", str(root), "--admin", "lorena", "--github", "lorena-gh", "--password-env", "PW_LORENA", "--no-sample-users")
    for login, profile in (("ana", "editor"), ("caio", "analyst"), ("bia", "viewer")):
        cli("user", "add", login, "--name", login.title(), "--github", f"{login}-gh", "--password-env", f"PW_{login.upper()}", root=root)
        cli("org", "member", "demo", login, profile, root=root)
    return root


@pytest.fixture()
def project(base_project, tmp_path, monkeypatch) -> Path:
    """Cópia isolada para testes que alteram o projeto."""
    dest = tmp_path / "p"
    shutil.copytree(base_project, dest)
    monkeypatch.setenv("UAI_MASTER_KEY", "0" * 43)
    monkeypatch.setenv("UAI_DB_DEMO", f"sqlite:///{dest}/demo/vendas.db")
    return dest
