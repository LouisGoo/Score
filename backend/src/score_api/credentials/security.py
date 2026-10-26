"""凭证规范化、HMAC 检索及供活动拥有者再次查看的认证加密。"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from score_api.core.config import Settings
from score_api.core.errors import APIError
from score_api.core.security import hash_secret

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_credential(value: str) -> str:
    # 先限制 ASCII，再转大写，避免 Unicode 大写展开被当作有效凭证。
    value = value.strip()
    if not re.fullmatch(r"[a-zA-Z0-9]{8,32}", value):
        raise ValueError("身份码需为 8～32 位 ASCII 字母数字")
    value = value.upper()
    if not re.search(r"[A-Z]", value) or not re.search(r"[0-9]", value):
        raise ValueError("身份码必须同时含字母和数字")
    return value


def generate_credential() -> str:
    while True:
        value = "".join(secrets.choice(ALPHABET) for _ in range(12))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return value


def credential_key(settings: Settings) -> bytes:
    if settings.credential_hmac_key is None:
        raise APIError(503, "CREDENTIAL_KEY_UNAVAILABLE", "身份服务尚未配置")
    return bytes.fromhex(settings.credential_hmac_key.get_secret_value())


def credential_lookup(settings: Settings, event_id: str, code: str) -> bytes:
    return hmac.new(
        credential_key(settings),
        (event_id + "\0" + normalize_credential(code)).encode("ascii"),
        hashlib.sha256,
    ).digest()


def credential_cipher(settings: Settings) -> AESGCM:
    # 从已有稳定密钥派生独立用途的加密密钥，不改变原有 HMAC 检索值。
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"score:credential-storage:v1"
    ).derive(credential_key(settings))
    return AESGCM(key)


def credential_context(event_id: str, judge_id: str, version: int) -> bytes:
    return f"score:credential:v1:{event_id}:{judge_id}:{version}".encode("ascii")


def encrypt_credential(
    settings: Settings, event_id: str, judge_id: str, version: int, code: str
) -> bytes:
    nonce = secrets.token_bytes(12)
    context = credential_context(event_id, judge_id, version)
    return (
        b"\x01" + nonce + credential_cipher(settings).encrypt(nonce, code.encode("ascii"), context)
    )


def decrypt_credential(
    settings: Settings, event_id: str, judge_id: str, version: int, ciphertext: bytes
) -> str:
    cipher = credential_cipher(settings)
    try:
        if not ciphertext.startswith(b"\x01"):
            raise ValueError("unsupported ciphertext version")
        code = cipher.decrypt(
            ciphertext[1:13], ciphertext[13:], credential_context(event_id, judge_id, version)
        ).decode("ascii")
        return normalize_credential(code)
    except (InvalidTag, ValueError) as exc:
        raise APIError(
            503, "CREDENTIAL_UNREADABLE", "身份码暂时无法读取，请联系管理员检查凭证密钥"
        ) from exc


@dataclass(frozen=True)
class PreparedCredential:
    code: str = field(repr=False)
    lookup: bytes = field(repr=False)
    encoded: str = field(repr=False)
    source: str


def prepare_credential(settings: Settings, event_id: str, manual: str | None):
    code = normalize_credential(manual) if manual is not None else generate_credential()
    lookup = credential_lookup(settings, event_id, code)
    return PreparedCredential(code, lookup, hash_secret(code), "manual" if manual else "generated")
