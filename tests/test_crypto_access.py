import pytest
from cryptography.exceptions import InvalidTag

from uai_data import access, crypto
from uai_data.config import Dashboard, DashboardAccess, Organization

ITER = 1000  # rápido nos testes; em produção são 600 mil


def test_encrypt_roundtrip_and_tamper():
    key = crypto.derive_key(crypto.new_master_key(), "dash:x")
    blob = crypto.encrypt(key, b'{"a": 1}' * 100, compress=True)
    assert crypto.decrypt(key, blob) == b'{"a": 1}' * 100
    tampered = bytearray(blob)
    tampered[0] ^= 1  # a flag é autenticada
    with pytest.raises(InvalidTag):
        crypto.decrypt(key, bytes(tampered))
    with pytest.raises(InvalidTag):
        crypto.decrypt(crypto.derive_key(crypto.new_master_key(), "dash:x"), blob)


def test_derive_key_is_deterministic():
    master = crypto.new_master_key()
    assert crypto.derive_key(master, "a") == crypto.derive_key(master, "a")
    assert crypto.derive_key(master, "a") != crypto.derive_key(master, "b")


def test_user_keys_login_and_wrap():
    keys = crypto.new_user_keys("senha-forte", ITER)
    private = crypto.unlock_private_key(keys.enc_private_key, keys.kdf_salt, ITER, "senha-forte")
    dk = crypto.derive_key(crypto.new_master_key(), "dash:y")
    wrapped = crypto.wrap_key(keys.public_key, dk)
    assert crypto.unwrap_key(private, wrapped) == dk
    with pytest.raises(InvalidTag):
        crypto.unlock_private_key(keys.enc_private_key, keys.kdf_salt, ITER, "errada")


def test_change_password_keeps_same_keypair():
    keys = crypto.new_user_keys("antiga", ITER)
    new = crypto.change_password(keys.enc_private_key, keys.kdf_salt, ITER, "antiga", "nova")
    assert new.public_key == keys.public_key
    crypto.unlock_private_key(new.enc_private_key, new.kdf_salt, new.kdf_iter, "nova")
    with pytest.raises(InvalidTag):
        crypto.unlock_private_key(new.enc_private_key, new.kdf_salt, new.kdf_iter, "antiga")


def _org():
    return Organization(
        name="AID", admins=["ana"],
        members={"bia": "viewer", "caio": "analyst", "duda": "editor"},
    )


def _dash(**access_kw):
    return Dashboard(
        title="t", organization="aid", database="main",
        cards=[{"id": "c", "title": "c", "source": {"table": "t"}}],
        access=DashboardAccess(**access_kw),
    )


def test_profiles_and_admin():
    org, dash = _org(), _dash()
    assert access.dashboard_perms(org, dash, "ana") == access.ALL
    assert access.dashboard_perms(org, dash, "bia") == {"view"}
    assert access.dashboard_perms(org, dash, "caio") == {"view", "download", "share"}
    assert "edit" in access.dashboard_perms(org, dash, "duda")
    assert access.dashboard_perms(org, dash, "estranho") == frozenset()


def test_private_dashboard_and_grants():
    org = _org()
    dash = _dash(private=True, grants={"bia": ["view"], "@editor": ["view", "edit"]})
    assert access.dashboard_perms(org, dash, "bia") == {"view"}
    assert access.dashboard_perms(org, dash, "caio") == frozenset()   # analyst não foi listado
    assert access.dashboard_perms(org, dash, "duda") == {"view", "edit"}
    assert access.dashboard_perms(org, dash, "ana") == access.ALL


def test_org_requires_admin_and_valid_profile():
    with pytest.raises(ValueError):
        Organization(name="x", admins=[])
    with pytest.raises(ValueError):
        Organization(name="x", admins=["a"], members={"b": "inexistente"})
