import json

import pytest
from conftest import PW, cli
from cryptography.exceptions import InvalidTag

from uai_data import crypto
from uai_data.builder import auth_name, build
from uai_data.config import Project


def login(site, project, user):
    auth = json.loads((site / "auth" / f"{auth_name(project, user)}.json").read_text())
    priv = crypto.unlock_private_key(auth["priv"], auth["kdf"]["salt"], auth["kdf"]["iter"], PW[user])
    me_key = crypto.unwrap_key(priv, auth["keys"]["@me"])
    me = json.loads(crypto.decrypt(me_key, (site / "auth" / f"{auth_name(project, user)}.me.bin").read_bytes()))
    return auth, priv, me


def test_build_login_and_permissions(project, tmp_path):
    p = Project.load(project)
    site = tmp_path / "site"
    stats = build(p, site)
    assert stats["dashboards"] == 1 and stats["cards"] == 17

    for user, can_download in (("lorena", True), ("ana", True), ("caio", True), ("bia", False)):
        auth, priv, me = login(site, p, user)
        dash = me["dashboards"][0]
        key = crypto.unwrap_key(priv, auth["keys"][dash["id"]])
        spec = json.loads(crypto.decrypt(key, (site / "d" / dash["id"] / "spec.bin").read_bytes()))
        assert spec["title"] == "Vendas — visão geral"
        assert (dash["id"] + "x" in auth["keys"]) is can_download, user
        if can_download:
            ek = crypto.unwrap_key(priv, auth["keys"][dash["id"] + "x"])
            assert crypto.decrypt(ek, (site / "x" / dash["id"] / "dashboard.xlsx.bin").read_bytes())[:2] == b"PK"
            assert crypto.decrypt(ek, (site / "x" / dash["id"] / "dashboard.pdf.bin").read_bytes())[:4] == b"%PDF"
            assert "download" in dash["perms"]
        else:
            assert "download" not in dash["perms"]
            with pytest.raises(InvalidTag):   # a chave de ver não abre o arquivo de baixar
                crypto.decrypt(key, (site / "x" / dash["id"] / "dashboard.xlsx.bin").read_bytes())

    # só o administrador enxerga a lista de pessoas
    assert "members" in login(site, p, "lorena")[2]["orgs"][0]
    assert "members" not in login(site, p, "bia")[2]["orgs"][0]
    # catálogo só para quem cria/edita
    assert login(site, p, "ana")[2]["orgs"][0]["catalog"] and not login(site, p, "bia")[2]["orgs"][0]["catalog"]
    # senha errada não abre nada
    auth = json.loads((site / "auth" / f"{auth_name(p, 'bia')}.json").read_text())
    with pytest.raises(InvalidTag):
        crypto.unlock_private_key(auth["priv"], auth["kdf"]["salt"], auth["kdf"]["iter"], "errada")


def test_removed_user_loses_access_to_new_data(project, tmp_path):
    p = Project.load(project)
    first = tmp_path / "site1"
    build(p, first)
    auth, priv, me = login(first, p, "bia")
    did = me["dashboards"][0]["id"]
    old_key = crypto.unwrap_key(priv, auth["keys"][did])

    cli("org", "remove", "demo", "bia", root=project)                    # atualiza o access.lock.json
    p2 = Project.load(project)
    second = tmp_path / "site2"
    build(p2, second, check_lock=True)
    new_card = (second / "c" / did / "faturamento.bin").read_bytes()
    with pytest.raises(InvalidTag):                                      # o que a Bia guardou não abre os dados novos
        crypto.decrypt(old_key, new_card)
    assert json.loads((second / "auth" / f"{auth_name(p2, 'bia')}.json").read_text())["keys"].keys() == {"@me"}


def test_share_epoch_rotates_links(project, tmp_path):
    p = Project.load(project)
    build(p, tmp_path / "a")
    f = project / "dashboards" / "demo" / "vendas.yml"
    f.write_text(f.read_text().replace("tags: [demo]", "tags: [demo]\nshare_epoch: 1"))
    build(Project.load(project), tmp_path / "b")
    did = next((tmp_path / "a" / "c").iterdir()).name
    assert (tmp_path / "a" / "c" / did / "faturamento.bin").read_bytes() != (tmp_path / "b" / "c" / did / "faturamento.bin").read_bytes()
    auth, priv, _ = login(tmp_path / "a", p, "lorena")
    old = crypto.unwrap_key(priv, auth["keys"][did])
    with pytest.raises(InvalidTag):
        crypto.decrypt(old, (tmp_path / "b" / "c" / did / "faturamento.bin").read_bytes())


def test_stale_lock_is_rejected_in_ci(project, tmp_path):
    from uai_data.config import ConfigError
    f = project / "access" / "demo.yml"
    f.write_text(f.read_text().replace("bia: viewer", "bia: editor"))        # permissão mudou, lock não
    with pytest.raises(ConfigError, match="access.lock.json"):
        build(Project.load(project), tmp_path / "a", check_lock=True)
    cli("lock", root=project)                                                 # o administrador atualiza o lock
    build(Project.load(project), tmp_path / "b", check_lock=True)


def test_missing_master_key(project, tmp_path, monkeypatch):
    monkeypatch.delenv("UAI_MASTER_KEY")
    from uai_data.config import ConfigError
    with pytest.raises(ConfigError, match="UAI_MASTER_KEY"):
        build(Project.load(project), tmp_path / "x")
