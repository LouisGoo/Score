from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCORE_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    app_name: str = "Score API"
    redis_url: SecretStr | None = None
    realtime_ticket_ttl_seconds: int = Field(default=30, ge=5, le=60)
    realtime_auth_interval_seconds: float = Field(default=30, ge=0.1, le=60)
    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    db_pool_timeout: float = Field(default=3, gt=0, le=30)
    db_pool_recycle: int = Field(default=300, gt=0)
    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    db_read_timeout: int = Field(default=5, ge=1, le=30)
    db_write_timeout: int = Field(default=5, ge=1, le=30)
    db_lock_wait_timeout: int = Field(default=3, ge=1, le=30)
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cookie_secure: bool = True
    session_ttl_seconds: int = Field(default=28800, ge=60, le=604800)
    login_window_seconds: int = Field(default=300, ge=1, le=3600)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    login_account_limit: int = Field(default=10, ge=1, le=100)
    credential_hmac_key: SecretStr | None = None
    judge_session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    judge_confirmation_ttl_seconds: int = Field(default=180, ge=30, le=600)
    judge_limit_window_seconds: int = Field(default=300, ge=1, le=3600)
    judge_source_limit: int = Field(default=600, ge=100, le=10000)
    judge_event_limit: int = Field(default=3000, ge=100, le=50000)
    judge_attempt_limit: int = Field(default=10, ge=1, le=100)

    @field_validator("credential_hmac_key")
    @classmethod
    def validate_credential_key(cls, value):
        if value is not None:
            raw = value.get_secret_value()
            if len(raw) != 64 or any(c not in "0123456789abcdefABCDEF" for c in raw):
                raise ValueError("凭证 HMAC 密钥必须为随机生成的 64 位十六进制字符串")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("至少配置一个可信 Origin")
        for origin in origins:
            parts = urlsplit(origin)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.path
                or parts.query
                or parts.fragment
                or "*" in origin
            ):
                raise ValueError("Origin 必须是无路径的明确 http/https 来源")
            _ = parts.port
        return origins
