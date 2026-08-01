from dataclasses import fields

import pytest

from subsystems.streaming.adapters.repositories.in_memory_session_repository import (
    InMemoryStreamSessionRepository,
)
from subsystems.streaming.domain import StreamSession, StreamSessionStatus


def _session() -> StreamSession:
    return StreamSession("trace", "broadcast", "title")


def test_session_transition_increments_version() -> None:
    prepared = _session().transition(StreamSessionStatus.PREPARING)
    assert prepared.status is StreamSessionStatus.PREPARING
    assert prepared.state_version == 1


def test_session_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="不正"):
        _session().transition(StreamSessionStatus.LIVE)


def test_session_repository_distinguishes_unknown_and_version_conflict() -> None:
    repository = InMemoryStreamSessionRepository()
    session = repository.create(_session())
    with pytest.raises(ValueError, match="未知"):
        repository.save(StreamSession("trace", "other", "title"))
    with pytest.raises(ValueError, match="state_version"):
        repository.save(session)


def test_session_model_has_no_credential_fields() -> None:
    names = {item.name for item in fields(StreamSession)}
    assert not names & {"access_token", "refresh_token", "credential", "password"}
