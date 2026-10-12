from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, SecretStr, StringConstraints, field_validator

from score_api.credentials.security import normalize_credential
from score_api.events.schemas import InputModel


class CredentialInput(InputModel):
    # 缺省/null 为自动生成；SecretStr 避免模型 repr 暴露请求凭证。
    code: SecretStr | None = Field(default=None, max_length=128)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return (
            SecretStr(normalize_credential(value.get_secret_value())) if value is not None else None
        )


class CredentialResult(InputModel):
    event_id: str
    judge_id: str
    code: str = Field(repr=False)
    credential_source: Literal["generated", "manual"]
    credential_version: int
    credential_updated_at: datetime


class ResetCredentialInput(CredentialInput):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
