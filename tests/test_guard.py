import shutil
import subprocess

import pytest

from uai_data.guard import check_pull_request


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


@pytest.fixture()
def repo(base_project, tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(base_project, root)
    (root / ".gitignore").write_text("site/\n.env\n.venv/\n")
    git(root, "init", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root


def pr(repo, edit):
    git(repo, "checkout", "-b", "pr")
    edit(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "pr")


def edit_dash(root):
    f = root / "dashboards" / "demo" / "vendas.yml"
    f.write_text(f.read_text().replace("Vendas — visão geral", "Vendas — novo título", 1))


def test_editor_can_edit_dashboard_viewer_cannot(repo):
    pr(repo, edit_dash)
    assert check_pull_request(repo, "main", "pr", "ana-gh") == []
    assert any("'edit'" in v for v in check_pull_request(repo, "main", "pr", "bia-gh"))
    assert any("'edit'" in v for v in check_pull_request(repo, "main", "pr", "desconhecido"))


def test_only_creators_add_dashboards(repo):
    def new(root):
        shutil.copy(root / "dashboards" / "demo" / "vendas.yml", root / "dashboards" / "demo" / "outro.yml")
    pr(repo, new)
    assert check_pull_request(repo, "main", "pr", "ana-gh") == []
    assert any("'create'" in v for v in check_pull_request(repo, "main", "pr", "caio-gh"))


def test_only_org_admin_changes_permissions(repo):
    def promote(root):
        f = root / "access" / "demo.yml"
        f.write_text(f.read_text().replace("bia: viewer", "bia: editor"))
    pr(repo, promote)
    assert check_pull_request(repo, "main", "pr", "lorena-gh") == []
    violations = check_pull_request(repo, "main", "pr", "ana-gh")      # editora tenta se dar poder
    assert any("administrador" in v for v in violations)


def test_pr_cannot_grant_itself_power(repo):
    """O PR tenta tornar quem o abriu administrador e editar na mesma mudança: vale a regra da main."""
    def sneaky(root):
        f = root / "access" / "demo.yml"
        f.write_text(f.read_text().replace("admins:\n- lorena", "admins:\n- lorena\n- bia"))
    pr(repo, sneaky)
    assert check_pull_request(repo, "main", "pr", "bia-gh") != []


def test_other_files_need_site_admin(repo):
    pr(repo, lambda r: (r / ".github" / "workflows" / "build.yml").write_text("name: x\n"))
    assert check_pull_request(repo, "main", "pr", "lorena-gh") == []
    assert check_pull_request(repo, "main", "pr", "ana-gh") != []


def test_lock_file_is_off_limits_in_prs(repo):
    pr(repo, lambda r: (r / "access.lock.json").write_text("{}\n"))
    assert any("access.lock.json" in v for v in check_pull_request(repo, "main", "pr", "ana-gh"))
    assert check_pull_request(repo, "main", "pr", "lorena-gh") == []
