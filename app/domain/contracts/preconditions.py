"""条件の意味を所有者に残す、明示的な実測公開と読取経路。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol

from .common import JsonValue, freeze_json, require_identifier, thaw_json
from .finalization import (
    AuthorityFinalizationParticipant,
    AuthorityGenerationToken,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
    authority_read_set,
)


class PreconditionFailure(str, Enum):
    INVALID_BINDING = "INVALID_BINDING"
    DUPLICATE_SOURCE = "DUPLICATE_SOURCE"
    UNREGISTERED_SOURCE = "UNREGISTERED_SOURCE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    INVALID_PUBLICATION = "INVALID_PUBLICATION"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    STALE_PUBLICATION = "STALE_PUBLICATION"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class PreconditionReadError(RuntimeError):
    """実測の取得失敗を、供給元の例外本文を含めず分類する。"""

    def __init__(self, failure: PreconditionFailure) -> None:
        self.failure = failure
        super().__init__(f"前提条件の実測を取得できません: {failure.value}")


@dataclass(frozen=True, slots=True)
class PreconditionSourceRef:
    owner_id: str
    contract_id: str

    def __post_init__(self) -> None:
        require_identifier(self.owner_id, "owner_id")
        require_identifier(self.contract_id, "contract_id")


@dataclass(frozen=True, slots=True)
class PreconditionSourceBinding:
    precondition_id: str
    subject_ref: str
    predicate: str
    source: PreconditionSourceRef

    def __post_init__(self) -> None:
        for name in ("precondition_id", "subject_ref", "predicate"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.source, PreconditionSourceRef):
            raise PreconditionReadError(PreconditionFailure.INVALID_BINDING)


def _strict_json(value: object, depth: int = 0) -> JsonValue:
    if depth > 32:
        raise PreconditionReadError(PreconditionFailure.CAPACITY_EXCEEDED)
    if value is None or type(value) in (str, bool, int, float):
        return freeze_json(value)
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("JSONのキーは厳密な文字列でなければなりません")
        return MappingProxyType({key: _strict_json(item, depth + 1) for key, item in value.items()})
    if isinstance(value, (tuple, list)) and type(value) in (tuple, list):
        return tuple(_strict_json(item, depth + 1) for item in value)
    raise ValueError("実測値は厳密なJSONでなければなりません")


@dataclass(frozen=True, slots=True)
class PreconditionObservation:
    binding: PreconditionSourceBinding
    actual: JsonValue

    def __post_init__(self) -> None:
        if not isinstance(self.binding, PreconditionSourceBinding):
            raise PreconditionReadError(PreconditionFailure.INVALID_BINDING)
        object.__setattr__(self, "actual", _strict_json(self.actual))

    def to_dict(self) -> dict[str, object]:
        return {
            "precondition_id": self.binding.precondition_id,
            "subject_ref": self.binding.subject_ref,
            "predicate": self.binding.predicate,
            "source": {
                "owner_id": self.binding.source.owner_id,
                "contract_id": self.binding.source.contract_id,
            },
            "actual": thaw_json(self.actual),
        }


class PreconditionSourceReader(Protocol):
    """所有者は実測値と全出典tokenを同じ同期読取で生成する。"""

    async def read_current(
        self, binding: PreconditionSourceBinding
    ) -> AuthorityReadPublication[PreconditionObservation]: ...


@dataclass(frozen=True, slots=True)
class PreconditionSourceRegistration:
    source: PreconditionSourceRef
    reader: PreconditionSourceReader
    participant: AuthorityFinalizationParticipant


class PreconditionSourceRouter:
    """信頼済み構成で固定した読取先を使い、述語を評価せず公開を照合する。"""

    def __init__(
        self,
        registrations: tuple[PreconditionSourceRegistration, ...],
        *,
        max_sources: int = 128,
        max_publication_bytes: int = 65536,
    ) -> None:
        for limit in (max_sources, max_publication_bytes):
            if type(limit) is not int or limit < 1:
                raise ValueError("公開上限は正の整数でなければなりません")
        if len(registrations) > max_sources:
            raise PreconditionReadError(PreconditionFailure.CAPACITY_EXCEEDED)
        sources: dict[PreconditionSourceRef, PreconditionSourceRegistration] = {}
        for registration in registrations:
            if (
                not isinstance(registration, PreconditionSourceRegistration)
                or not isinstance(registration.source, PreconditionSourceRef)
                or not isinstance(registration.participant, AuthorityFinalizationParticipant)
                or not callable(getattr(registration.reader, "read_current", None))
            ):
                raise PreconditionReadError(PreconditionFailure.INVALID_BINDING)
            if registration.source in sources:
                raise PreconditionReadError(PreconditionFailure.DUPLICATE_SOURCE)
            try:
                owner_identity = registration.participant.token().owner_identity
            except FinalizationError:
                raise PreconditionReadError(PreconditionFailure.SOURCE_UNAVAILABLE) from None
            if owner_identity != registration.source.owner_id:
                raise PreconditionReadError(PreconditionFailure.IDENTITY_MISMATCH)
            sources[registration.source] = registration
        self._sources = MappingProxyType(sources)
        self._max_publication_bytes = max_publication_bytes

    async def read_current(
        self, binding: PreconditionSourceBinding
    ) -> AuthorityReadPublication[PreconditionObservation]:
        if not isinstance(binding, PreconditionSourceBinding):
            raise PreconditionReadError(PreconditionFailure.INVALID_BINDING)
        registration = self._sources.get(binding.source)
        if registration is None:
            raise PreconditionReadError(PreconditionFailure.UNREGISTERED_SOURCE)

        # Python 3.10でも取消の捕捉を成功へ読み替えず、再取消中も回収する。
        async def read() -> AuthorityReadPublication[PreconditionObservation]:
            return await registration.reader.read_current(binding)

        task = asyncio.create_task(read())
        try:
            publication = await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise
        except PreconditionReadError:
            raise
        except Exception:
            raise PreconditionReadError(PreconditionFailure.SOURCE_UNAVAILABLE) from None
        if (
            not isinstance(publication, AuthorityReadPublication)
            or not isinstance(publication.value, PreconditionObservation)
            or type(publication.tokens) is not tuple
            or not publication.tokens
            or any(not isinstance(t, AuthorityGenerationToken) for t in publication.tokens)
        ):
            raise PreconditionReadError(PreconditionFailure.INVALID_PUBLICATION)
        if publication.value.binding != binding:
            raise PreconditionReadError(PreconditionFailure.IDENTITY_MISMATCH)
        size = len(
            json.dumps(
                publication.value.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if size > self._max_publication_bytes:
            raise PreconditionReadError(PreconditionFailure.CAPACITY_EXCEEDED)
        participants = {registration.participant}
        pending = [registration.participant]
        while pending:
            for dependency in pending.pop().dependencies:
                if dependency not in participants:
                    participants.add(dependency)
                    pending.append(dependency)
        if len(participants) > 16 or len(publication.tokens) != len(participants):
            raise PreconditionReadError(PreconditionFailure.INVALID_PUBLICATION)
        if any(
            not isinstance(t._participant, AuthorityFinalizationParticipant)
            for t in publication.tokens
        ):
            raise PreconditionReadError(PreconditionFailure.INVALID_PUBLICATION)
        if {t._participant for t in publication.tokens} != participants:
            raise PreconditionReadError(PreconditionFailure.IDENTITY_MISMATCH)
        try:
            with authority_read_set(tuple(participants)):
                for token in publication.tokens:
                    # 同じFoundation内の#632検査を再利用し、世代検査を複製しない。
                    failure = token._participant._validate(token)
                    if failure is not None:
                        raise FinalizationError(failure)
        except FinalizationError as error:
            code = (
                PreconditionFailure.STALE_PUBLICATION
                if error.failure is FinalizationFailure.GENERATION_MISMATCH
                else PreconditionFailure.SOURCE_UNAVAILABLE
            )
            raise PreconditionReadError(code) from None
        return publication
