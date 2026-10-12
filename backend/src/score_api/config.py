from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCORE_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    app_name: str = "Score API"
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
