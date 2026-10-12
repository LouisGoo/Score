"""凭证规范化、随机生成和活动隔离的 HMAC；明文仅短暂存在于内存。"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

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
