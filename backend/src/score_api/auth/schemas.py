"""认证 HTTP 请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from score_api.core.security import normalize_login


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("login")
    @classmethod
    def valid_login(cls, value: str) -> str:
        return normalize_login(value)


class AdminInfo(BaseModel):
    id: str
    login: str


class SessionInfo(BaseModel):
    admin: AdminInfo
    expires_at: datetime
    csrf_token: str


class CSRFInfo(BaseModel):
    csrf_token: str
