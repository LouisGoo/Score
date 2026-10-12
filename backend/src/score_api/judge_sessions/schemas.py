from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, SecretStr, StringConstraints

from score_api.core.security import TOKEN_PATTERN
from score_api.credentials.schemas import CredentialInput
from score_api.events.publication_schemas import FrozenJudge
from score_api.events.schemas import InputModel


def normalize_public_code(value):
    return value.upper()


PublicCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9]{12}$"),
    AfterValidator(normalize_public_code),
]


class VerifyInput(CredentialInput):
    public_code: PublicCode
    code: SecretStr = Field(max_length=128)


def valid_token(value):
    if not TOKEN_PATTERN.fullmatch(value.get_secret_value()):
        raise ValueError("无效确认令牌")
    return value


class ExchangeInput(InputModel):
    confirmation_token: Annotated[SecretStr, AfterValidator(valid_token)]


class PreviewInfo(InputModel):
    public_code: str
    title: str
    description: str
    organization: str
    planned_at: datetime | None
    status: Literal["READY", "RUNNING", "FINISHED", "ARCHIVED"]
    exchange_open: bool


class ConfirmationInfo(InputModel):
    judge: FrozenJudge
    confirmation_token: str = Field(repr=False)
    expires_at: datetime


class JudgeSessionInfo(InputModel):
    judge: FrozenJudge
    expires_at: datetime
    csrf_token: str = Field(repr=False)
    read_only: bool
