"""Criptografia do Uai Data.

Como o site é estático (GitHub Pages), o "login" é criptográfico:

    senha ──PBKDF2──▶ chave ──AES-GCM──▶ chave privada RSA do usuário
                                              │ (RSA-OAEP)
                                              ▼
                              chave de dados (DK) de cada painel
                                              │ (AES-GCM)
                                              ▼
                              dados do painel, publicados cifrados

Quem não tem permissão não recebe a DK do painel, então não consegue ler os dados — mesmo
que baixe todos os arquivos do site. A senha nunca é gravada; só a chave privada cifrada.
O navegador faz exatamente as mesmas operações com a Web Crypto API (veja web/crypto.js).
"""

from __future__ import annotations

import base64
import gzip
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

RSA_BITS = 3072
IV_BYTES = 12
FLAG_RAW, FLAG_GZIP = b"\x00", b"\x01"


# ----------------------------------------------------------------------- base64
def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def b64u_e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64u_d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ----------------------------------------------------------------------- chaves simétricas
def new_master_key() -> str:
    """Segredo do projeto (vai para o GitHub Secrets como UAI_MASTER_KEY)."""
    return b64u_e(os.urandom(32))


def derive_key(master_b64u: str, info: str) -> bytes:
    """Chave de 256 bits determinística: o mesmo (master, info) sempre dá a mesma chave.

    É isso que permite que links de compartilhamento continuem válidos entre builds.
    """
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info.encode()).derive(
        b64u_d(master_b64u)
    )


def derive_id(master_b64u: str, info: str, size: int = 10) -> str:
    """Identificador opaco (não revela o nome do painel nas URLs do site)."""
    return derive_key(master_b64u, "id:" + info).hex()[: size * 2]


def encrypt(key: bytes, plaintext: bytes, compress: bool = False) -> bytes:
    """Formato do arquivo: [flag 1B][iv 12B][ciphertext+tag]. A flag é autenticada (AAD)."""
    flag = FLAG_GZIP if compress else FLAG_RAW
    body = gzip.compress(plaintext, compresslevel=6, mtime=0) if compress else plaintext
    iv = os.urandom(IV_BYTES)
    return flag + iv + AESGCM(key).encrypt(iv, body, flag)


def decrypt(key: bytes, blob: bytes) -> bytes:
    flag, iv, ct = blob[:1], blob[1 : 1 + IV_BYTES], blob[1 + IV_BYTES :]
    body = AESGCM(key).decrypt(iv, ct, flag)
    return gzip.decompress(body) if flag == FLAG_GZIP else body


# ----------------------------------------------------------------------- usuário
@dataclass
class UserKeys:
    public_key: str          # SPKI DER em base64
    kdf_salt: str            # base64
    kdf_iter: int
    enc_private_key: str     # base64(iv || AES-GCM(PKCS8 DER))


def _password_key(password: str, salt: bytes, iterations: int) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    ).derive(password.encode("utf-8"))


def new_user_keys(password: str, iterations: int = 600_000) -> UserKeys:
    private = rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)
    return _seal_private(private, password, iterations)


def _seal_private(private: rsa.RSAPrivateKey, password: str, iterations: int) -> UserKeys:
    der_private = private.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    der_public = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    salt, iv = os.urandom(16), os.urandom(IV_BYTES)
    key = _password_key(password, salt, iterations)
    sealed = iv + AESGCM(key).encrypt(iv, der_private, b"uai-private-key")
    return UserKeys(b64e(der_public), b64e(salt), iterations, b64e(sealed))


def unlock_private_key(enc_private_key: str, salt: str, iterations: int, password: str):
    """Abre a chave privada. Senha errada => InvalidTag (o GCM é a verificação de senha)."""
    blob = b64d(enc_private_key)
    key = _password_key(password, b64d(salt), iterations)
    der = AESGCM(key).decrypt(blob[:IV_BYTES], blob[IV_BYTES:], b"uai-private-key")
    return serialization.load_der_private_key(der, password=None)


def change_password(enc_private_key: str, salt: str, iterations: int, old: str, new: str,
                    new_iterations: int | None = None) -> UserKeys:
    private = unlock_private_key(enc_private_key, salt, iterations, old)
    return _seal_private(private, new, new_iterations or iterations)


_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def wrap_key(public_key_b64: str, key: bytes) -> str:
    public = serialization.load_der_public_key(b64d(public_key_b64))
    return b64e(public.encrypt(key, _OAEP))


def unwrap_key(private_key, wrapped_b64: str) -> bytes:
    return private_key.decrypt(b64d(wrapped_b64), _OAEP)
