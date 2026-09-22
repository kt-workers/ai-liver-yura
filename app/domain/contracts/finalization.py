"""正規所有者の世代公開と短い同期確定を同じ排他境界で保護する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from inspect import iscoroutinefunction
from threading import Event, Lock, RLock, local
from types import MethodType
from typing import Concatenate, Generic, ParamSpec, Protocol, TypeVar
from uuid import uuid4
from weakref import ReferenceType, WeakKeyDictionary, WeakValueDictionary, ref


class FinalizationFailure(str, Enum):
    GENERATION_MISMATCH = "GENERATION_MISMATCH"
    PARTICIPANT_UNAVAILABLE = "PARTICIPANT_UNAVAILABLE"
    PARTICIPANT_UNSUPPORTED = "PARTICIPANT_UNSUPPORTED"
    INVALID_PARTICIPANT = "INVALID_PARTICIPANT"
    INVALID_LOCK_CONFIGURATION = "INVALID_LOCK_CONFIGURATION"
    PARTICIPANT_BUSY = "PARTICIPANT_BUSY"
    CANCELLED = "CANCELLED"
    TARGET_ALREADY_FINALIZED = "TARGET_ALREADY_FINALIZED"
    TARGET_REJECTED = "TARGET_REJECTED"
    TARGET_COMMIT_FAULT = "TARGET_COMMIT_FAULT"


class FinalizationError(RuntimeError):
    """同期境界の違反を秘密を含まない固定分類で通知する。"""

    def __init__(self, failure: FinalizationFailure) -> None:
        self.failure = failure
        super().__init__(f"所有者の同期境界を利用できません: {failure.value}")


@dataclass(frozen=True, slots=True)
class _GenerationSeal:
    generation: int


@dataclass(frozen=True, slots=True)
class AuthorityGenerationToken:
    owner_identity: str
    owner_instance_key: str
    participant_identity: str
    generation: int
    _participant: AuthorityFinalizationParticipant = field(repr=False, compare=False)
    _seal: _GenerationSeal = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("世代は非負の厳密な整数でなければなりません")


T = TypeVar("T")
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
P = ParamSpec("P")


@dataclass(frozen=True, slots=True)
class AuthorityReadPublication(Generic[T]):
    value: T
    tokens: tuple[AuthorityGenerationToken, ...]


@dataclass(frozen=True, slots=True)
class AuthorityFinalizationResult(Generic[OutputT]):
    value: OutputT | None = None
    failure: FinalizationFailure | None = None
    source_tokens: tuple[AuthorityGenerationToken, ...] = ()
    target_token: AuthorityGenerationToken | None = None


@dataclass(frozen=True, slots=True)
class AuthorityFinalizationOperation(Generic[InputT, OutputT]):
    participant: AuthorityFinalizationParticipant
    operation_identity: str
    dependencies: tuple[AuthorityFinalizationParticipant, ...]
    _invoke: Callable[[InputT, datetime], OutputT] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class AuthorityFinalizationRequest(Generic[InputT, OutputT]):
    expected_tokens: tuple[AuthorityGenerationToken, ...]
    target: AuthorityFinalizationParticipant
    operation: AuthorityFinalizationOperation[InputT, OutputT]
    payload: InputT


@dataclass
class _ThreadState:
    held: list[AuthorityFinalizationParticipant] = field(default_factory=list)
    fence: bool = False
    allowed: tuple[AuthorityFinalizationParticipant, ...] = ()
    target: AuthorityFinalizationParticipant | None = None
    committing: bool = False


_thread = local()
_registration_lock = Lock()
_owners: WeakKeyDictionary[object, ReferenceType[AuthorityFinalizationParticipant]] = (
    WeakKeyDictionary()
)
_keys: WeakValueDictionary[tuple[int, str], AuthorityFinalizationParticipant] = (
    WeakValueDictionary()
)


def _state() -> _ThreadState:
    state = getattr(_thread, "state", None)
    if not isinstance(state, _ThreadState):
        state = _ThreadState()
        _thread.state = state
    return state


class AuthorityFinalizationParticipant:
    """一所有者の同期プリミティブと機械的な世代を所有する。"""

    def __init__(
        self,
        owner: object,
        owner_identity: str,
        lock_rank: int,
        *,
        owner_instance_key: str | None = None,
        supports_finalization: bool = True,
    ) -> None:
        if not owner_identity or type(lock_rank) is not int or lock_rank < 0:
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        key = uuid4().hex if owner_instance_key is None else owner_instance_key
        if not isinstance(key, str) or not key:
            raise FinalizationError(FinalizationFailure.INVALID_PARTICIPANT)
        self._owner_identity = owner_identity
        self._instance_key = key
        self._identity = uuid4().hex
        self._rank = lock_rank
        self._primitive = RLock()
        self._generation = 0
        self._seal = _GenerationSeal(0)
        self._available = True
        self._supported = supports_finalization
        self._dependencies: tuple[AuthorityFinalizationParticipant, ...] = ()
        self._operations: dict[str, object] = {}
        with _registration_lock:
            if owner in _owners or (lock_rank, key) in _keys:
                raise FinalizationError(FinalizationFailure.INVALID_PARTICIPANT)
            _owners[owner] = ref(self)
            _keys[(lock_rank, key)] = self

    @property
    def order_key(self) -> tuple[int, str]:
        return self._rank, self._instance_key

    @property
    def dependencies(self) -> tuple[AuthorityFinalizationParticipant, ...]:
        return self._dependencies

    def configure_dependencies(
        self,
        dependencies: tuple[AuthorityFinalizationParticipant, ...],
    ) -> None:
        """構成時に通常の所有者間読取が同じ全順序に従うことを検査する。"""
        if any(p is self or p.order_key <= self.order_key for p in dependencies):
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        with self:
            if self._dependencies or self._generation:
                raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
            self._dependencies = tuple(dependencies)

    def __enter__(self) -> AuthorityFinalizationParticipant:
        self._acquire(blocking=True)
        if not self._available:
            self._release()
            raise FinalizationError(FinalizationFailure.PARTICIPANT_UNAVAILABLE)
        return self

    def __exit__(self, *args: object) -> None:
        self._release()

    def _acquire(self, *, blocking: bool) -> bool:
        state = _state()
        if state.fence and self not in state.allowed:
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        if (
            self not in state.held
            and state.held
            and self.order_key < max(p.order_key for p in state.held)
        ):
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        if not self._primitive.acquire(blocking=blocking):
            return False
        state.held.append(self)
        return True

    def _release(self) -> None:
        state = _state()
        if not state.held or state.held[-1] is not self:
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        state.held.pop()
        self._primitive.release()

    def _advance(self) -> None:
        self._generation += 1
        self._seal = _GenerationSeal(self._generation)

    @contextmanager
    def mutation(self) -> Iterator[None]:
        with self:
            state = _state()
            if state.fence and (not state.committing or state.target is not self):
                raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
            self._advance()
            yield

    def token(self) -> AuthorityGenerationToken:
        with self:
            if not self._supported:
                raise FinalizationError(FinalizationFailure.PARTICIPANT_UNSUPPORTED)
            return AuthorityGenerationToken(
                self._owner_identity,
                self._instance_key,
                self._identity,
                self._generation,
                self,
                self._seal,
            )

    def retire(self) -> None:
        """利用不能と失効を同じ境界で公開する。"""
        with self.mutation():
            self._available = False

    def register_operation(
        self,
        owner: object,
        operation_identity: str,
        invoke: Callable[[InputT, datetime], OutputT],
        dependencies: tuple[AuthorityFinalizationParticipant, ...] = (),
    ) -> AuthorityFinalizationOperation[InputT, OutputT]:
        """信頼済み構成で監査した所有者の同期メソッドだけを登録する。"""
        with _registration_lock:
            registered = _owners.get(owner)
        if (
            (registered is None or registered() is not self)
            or not isinstance(invoke, MethodType)
            or invoke.__self__ is not owner
            or getattr(type(owner), invoke.__name__, None) is not invoke.__func__
            or not operation_identity
            or iscoroutinefunction(invoke)
        ):
            raise FinalizationError(FinalizationFailure.INVALID_PARTICIPANT)
        dependencies = tuple(dependencies)
        if any(not isinstance(p, AuthorityFinalizationParticipant) for p in dependencies):
            raise FinalizationError(FinalizationFailure.PARTICIPANT_UNSUPPORTED)
        if any(p is not self and p.order_key <= self.order_key for p in dependencies):
            raise FinalizationError(FinalizationFailure.INVALID_LOCK_CONFIGURATION)
        operation = AuthorityFinalizationOperation(self, operation_identity, dependencies, invoke)
        with self:
            if operation_identity in self._operations:
                raise FinalizationError(FinalizationFailure.INVALID_PARTICIPANT)
            # 登録済み参照の照合だけに使い、型付き呼出しは要求の操作参照を使う。
            self._operations[operation_identity] = operation
        return operation

    def _validate(self, token: AuthorityGenerationToken) -> FinalizationFailure | None:
        if (
            token._participant is not self
            or token.owner_identity != self._owner_identity
            or token.owner_instance_key != self._instance_key
            or token.participant_identity != self._identity
            or not isinstance(token._seal, _GenerationSeal)
            or token._seal.generation != token.generation
        ):
            return FinalizationFailure.INVALID_PARTICIPANT
        if not self._supported:
            return FinalizationFailure.PARTICIPANT_UNSUPPORTED
        if not self._available:
            return FinalizationFailure.PARTICIPANT_UNAVAILABLE
        if token.generation != self._generation:
            return FinalizationFailure.GENERATION_MISMATCH
        if token._seal is not self._seal:
            return FinalizationFailure.INVALID_PARTICIPANT
        return None


class ParticipatingAuthority(Protocol):
    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant: ...


A = TypeVar("A", bound=ParticipatingAuthority)


def authority_mutation(method: Callable[Concatenate[A, P], T]) -> Callable[Concatenate[A, P], T]:
    """検査失敗を含む更新可能操作の入口で旧世代を失効する。"""

    @wraps(method)
    def wrapped(self: A, /, *args: P.args, **kwargs: P.kwargs) -> T:
        with self.finalization_participant.mutation():
            return method(self, *args, **kwargs)

    return wrapped


@contextmanager
def authority_read_set(
    participants: tuple[AuthorityFinalizationParticipant, ...],
) -> Iterator[tuple[AuthorityFinalizationParticipant, ...]]:
    """複合読取を同じ順序で保護し、公開値と全出典の世代を結ぶ。"""
    ordered = tuple(sorted(set(participants), key=lambda p: p.order_key))
    acquired: list[AuthorityFinalizationParticipant] = []
    try:
        for participant in ordered:
            participant.__enter__()
            acquired.append(participant)
        yield ordered
    finally:
        for participant in reversed(acquired):
            participant.__exit__()


class AuthorityFinalizationFence:
    def __init__(self, *, max_participants: int = 16) -> None:
        if type(max_participants) is not int or max_participants < 1:
            raise ValueError("参加者上限は正の厳密な整数でなければなりません")
        self._max_participants = max_participants

    def finalize(
        self,
        request: AuthorityFinalizationRequest[InputT, OutputT],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[OutputT]:
        state = _state()
        if state.fence or state.held:
            return AuthorityFinalizationResult(
                failure=FinalizationFailure.INVALID_LOCK_CONFIGURATION
            )
        if not isinstance(request, AuthorityFinalizationRequest):
            return AuthorityFinalizationResult(failure=FinalizationFailure.INVALID_PARTICIPANT)
        operation = request.operation
        target = request.target
        if not isinstance(target, AuthorityFinalizationParticipant):
            return AuthorityFinalizationResult(failure=FinalizationFailure.PARTICIPANT_UNSUPPORTED)
        if (
            not isinstance(operation, AuthorityFinalizationOperation)
            or operation.participant is not target
            or target._operations.get(operation.operation_identity) is not operation
        ):
            return AuthorityFinalizationResult(failure=FinalizationFailure.INVALID_PARTICIPANT)
        if not request.expected_tokens:
            return AuthorityFinalizationResult(
                failure=FinalizationFailure.INVALID_LOCK_CONFIGURATION
            )
        expected: dict[AuthorityFinalizationParticipant, AuthorityGenerationToken] = {}
        for token in request.expected_tokens:
            if not isinstance(token, AuthorityGenerationToken) or not isinstance(
                token._participant, AuthorityFinalizationParticipant
            ):
                return AuthorityFinalizationResult(failure=FinalizationFailure.INVALID_PARTICIPANT)
            participant = token._participant
            previous = expected.get(participant)
            if previous is not None and (previous != token or previous._seal is not token._seal):
                return AuthorityFinalizationResult(failure=FinalizationFailure.INVALID_PARTICIPANT)
            expected[participant] = token
        required = set(operation.dependencies) | set(target.dependencies)
        for participant in expected:
            required.update(participant.dependencies)
        if not required <= set(expected):
            return AuthorityFinalizationResult(
                failure=FinalizationFailure.INVALID_LOCK_CONFIGURATION
            )
        participants = tuple(sorted(set(expected) | {target}, key=lambda p: p.order_key))
        if len(participants) > self._max_participants or len(
            {p.order_key for p in participants}
        ) != len(participants):
            return AuthorityFinalizationResult(
                failure=FinalizationFailure.INVALID_LOCK_CONFIGURATION
            )
        acquired: list[AuthorityFinalizationParticipant] = []
        state.fence = True
        state.allowed = participants
        state.target = target
        try:
            for participant in participants:
                if cancellation is not None and cancellation.is_set():
                    return AuthorityFinalizationResult(failure=FinalizationFailure.CANCELLED)
                if not participant._acquire(blocking=False):
                    return AuthorityFinalizationResult(failure=FinalizationFailure.PARTICIPANT_BUSY)
                acquired.append(participant)
            if cancellation is not None and cancellation.is_set():
                return AuthorityFinalizationResult(failure=FinalizationFailure.CANCELLED)
            if not target._supported:
                return AuthorityFinalizationResult(
                    failure=FinalizationFailure.PARTICIPANT_UNSUPPORTED
                )
            if not target._available:
                return AuthorityFinalizationResult(
                    failure=FinalizationFailure.PARTICIPANT_UNAVAILABLE
                )
            for participant, token in expected.items():
                failure = participant._validate(token)
                if failure is not None:
                    return AuthorityFinalizationResult(failure=failure)
            if cancellation is not None and cancellation.is_set():
                return AuthorityFinalizationResult(failure=FinalizationFailure.CANCELLED)
            state.committing = True
            # 確定先操作へ入った時点で失効し、拒否でも製品リビジョンは偽らない。
            target._advance()
            try:
                value = operation._invoke(request.payload, datetime.now(timezone.utc))
            except FinalizationError as error:
                if error.failure in (
                    FinalizationFailure.TARGET_REJECTED,
                    FinalizationFailure.TARGET_ALREADY_FINALIZED,
                ):
                    return AuthorityFinalizationResult(failure=error.failure)
                target._available = False
                target._advance()
                return AuthorityFinalizationResult(
                    failure=error.failure
                    if error.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
                    else FinalizationFailure.TARGET_COMMIT_FAULT
                )
            except BaseException:
                target._available = False
                target._advance()
                return AuthorityFinalizationResult(failure=FinalizationFailure.TARGET_COMMIT_FAULT)
            return AuthorityFinalizationResult(
                value=value,
                source_tokens=tuple(expected.values()),
                target_token=target.token(),
            )
        finally:
            state.committing = False
            for participant in reversed(acquired):
                participant._release()
            state.fence = False
            state.allowed = ()
            state.target = None
