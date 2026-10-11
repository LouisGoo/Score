from pydantic import Field, SecretStr
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
