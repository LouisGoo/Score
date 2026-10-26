import pytest
from pydantic import ValidationError

from score_api.core.config import Settings
from score_api.core.errors import APIError
from score_api.core.security import verify_password
from score_api.credentials.schemas import CredentialInput
from score_api.credentials.security import (
    credential_lookup,
    decrypt_credential,
    encrypt_credential,
    generate_credential,
    normalize_credential,
    prepare_credential,
)


@pytest.mark.parametrize(
    "code",
    [
        "",
        "12345678",
        "abcdefgh",
        "abc1234",
        "a1" * 17,
        "ABC 12345",
        "ßABC1234",
        "ＡBC12345",
        "ABC１２３４５",
    ],
)
def test_invalid_codes(code):
    with pytest.raises(ValidationError):
        CredentialInput(code=code)


def test_normalization_generation_and_secret_representations():
    assert normalize_credential("  abcd1234\n") == "ABCD1234"
    assert "abcd1234" not in repr(CredentialInput(code="abcd1234"))
    for _ in range(100):
        code = generate_credential()
        assert len(code) == 12 and normalize_credential(code) == code
        assert not set(code) & set("01IO")


def test_hash_and_hmac_are_salted_keyed_and_scoped():
    settings = Settings(_env_file=None, credential_hmac_key="ab" * 32)
    first = prepare_credential(settings, "event", "ABCD1234")
    second = prepare_credential(settings, "event", "abcd1234")
    assert first.lookup == second.lookup and first.encoded != second.encoded
    assert verify_password(first.code, first.encoded)
    assert not verify_password("WRONG123", first.encoded)
    assert first.lookup != credential_lookup(settings, "other", first.code)
    assert first.lookup != credential_lookup(
        Settings(_env_file=None, credential_hmac_key="cd" * 32), "event", first.code
    )
    assert first.code not in repr(first) and first.encoded not in repr(first)
    with pytest.raises(APIError, match="身份服务尚未配置"):
        prepare_credential(Settings(_env_file=None), "event", "ABCD1234")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, credential_hmac_key="weak")


def test_encrypted_credentials_are_randomized_and_bound_to_owner_record():
    settings = Settings(_env_file=None, credential_hmac_key="ab" * 32)
    code = "ABCD1234"
    ciphertext = encrypt_credential(settings, "event", "judge", 1, code)
    assert code.encode() not in ciphertext
    assert ciphertext != encrypt_credential(settings, "event", "judge", 1, code)
    assert decrypt_credential(settings, "event", "judge", 1, ciphertext) == code
    for event_id, judge_id, version in (
        ("other", "judge", 1),
        ("event", "other", 1),
        ("event", "judge", 2),
    ):
        with pytest.raises(APIError) as error:
            decrypt_credential(settings, event_id, judge_id, version, ciphertext)
        assert error.value.code == "CREDENTIAL_UNREADABLE"
    for damaged in (
        b"",
        b"\x01",
        b"\x02" + ciphertext[1:],
        ciphertext[:-1],
        ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]),
    ):
        with pytest.raises(APIError) as error:
            decrypt_credential(settings, "event", "judge", 1, damaged)
        assert error.value.code == "CREDENTIAL_UNREADABLE"
    with pytest.raises(APIError) as error:
        decrypt_credential(
            Settings(_env_file=None, credential_hmac_key="cd" * 32), "event", "judge", 1, ciphertext
        )
    assert error.value.code == "CREDENTIAL_UNREADABLE"
