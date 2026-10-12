"""密码使用标准库 scrypt；随机会话令牌仅保存 SHA-256 摘要。"""

import hashlib
import re
import secrets
from threading import BoundedSemaphore

from score_api.core.errors import APIError

PASSWORD_SLOTS = BoundedSemaphore(2)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
LOGIN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")


def normalize_login(value: str) -> str:
    result = value.strip().lower()
    if not LOGIN_PATTERN.fullmatch(result):
        raise ValueError("账号需为 3～64 位 ASCII 字母、数字、点、下划线或连字符")
    return result


def password_digest(password: str, salt: bytes) -> bytes:
    # 限制单进程同时进行的高内存哈希；不占用数据库连接等待计算。
    if not PASSWORD_SLOTS.acquire(blocking=False):
        raise APIError(503, "AUTH_BUSY", "认证繁忙，请稍后重试", retry_after=1)
    try:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**17,
            r=8,
            p=1,
            maxmem=256 * 1024 * 1024,
            dklen=32,
        )
    finally:
        PASSWORD_SLOTS.release()


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("密码长度必须为 12～128 个字符")
    salt = secrets.token_bytes(16)
    digest = password_digest(password, salt)
    return f"scrypt$131072$8$1${salt.hex()}${digest.hex()}"


# 不存在的账号也执行同等成本的计算；这不是可用账号的密码哈希。
DUMMY_HASH = "scrypt$131072$8$1$" + "00" * 16 + "$" + "00" * 32


def verify_password(password: str, encoded: str) -> bool:
    if len(password) > 128:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "131072", "8", "1"):
            return False
        salt_bytes, expected_bytes = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt_bytes) != 16 or len(expected_bytes) != 32:
            return False
    except ValueError:
        return False
    return secrets.compare_digest(password_digest(password, salt_bytes), expected_bytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_csrf(token: str) -> str:
    return token_hash("score-admin-csrf:" + token)
