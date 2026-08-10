from __future__ import annotations

from cloud_validation.character_reference_lab_session import CharacterReferenceLabSession


def test_session_token_is_valid_until_expiry() -> None:
    sessions = CharacterReferenceLabSession(
        username="tester",
        password="secret",
        ttl_seconds=100,
    )

    token = sessions.issue(now=1_000)

    assert sessions.validate(token, now=1_099) is True
    assert sessions.validate(token, now=1_100) is False


def test_session_token_rejects_wrong_password_or_tampering() -> None:
    issuer = CharacterReferenceLabSession(username="tester", password="secret")
    other = CharacterReferenceLabSession(username="tester", password="different")
    token = issuer.issue(now=1_000)

    assert other.validate(token, now=1_001) is False
    assert issuer.validate(token + "x", now=1_001) is False


def test_login_credentials_use_existing_lab_secret() -> None:
    sessions = CharacterReferenceLabSession(username="tester", password="secret")

    assert sessions.validate_credentials("tester", "secret") is True
    assert sessions.validate_credentials("tester", "wrong") is False
    assert sessions.validate_credentials("wrong", "secret") is False
