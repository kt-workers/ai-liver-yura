"""意味を持たない共通読取境界を、明示した試験所有者で検証する。"""

import asyncio
from dataclasses import replace
from enum import IntEnum
from typing import cast

import pytest

from app.domain.contracts.common import JsonValue, PreconditionRef
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
)
from app.domain.contracts.preconditions import (
    PreconditionFailure,
    PreconditionObservation,
    PreconditionReadError,
    PreconditionSourceBinding,
    PreconditionSourceRef,
    PreconditionSourceRegistration,
    PreconditionSourceRouter,
)

SOURCE = PreconditionSourceRef("試験所有者", "試験公開")
BINDING = PreconditionSourceBinding("条件A", "対象A", "評価しない述語", SOURCE)


class Owner:
    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, SOURCE.owner_id, 10)
        self.actual: JsonValue = False
        self.override: AuthorityReadPublication[PreconditionObservation] | None = None
        self.calls = 0

    async def read_current(
        self, binding: PreconditionSourceBinding
    ) -> AuthorityReadPublication[PreconditionObservation]:
        self.calls += 1
        if self.override is not None:
            return self.override
        with self.participant:
            return AuthorityReadPublication(
                PreconditionObservation(binding, self.actual), (self.participant.token(),)
            )

    def router(self, **kwargs: int) -> PreconditionSourceRouter:
        return PreconditionSourceRouter(
            (PreconditionSourceRegistration(SOURCE, self, self.participant),), **kwargs
        )


@pytest.mark.parametrize("field", ["owner_id", "contract_id"])
def test_source_identity(field: str) -> None:
    with pytest.raises(ValueError):
        replace(SOURCE, **{field: " "})


@pytest.mark.parametrize("field", ["precondition_id", "subject_ref", "predicate"])
def test_binding_identity(field: str) -> None:
    with pytest.raises(ValueError):
        PreconditionSourceBinding(
            "" if field == "precondition_id" else "条件",
            "" if field == "subject_ref" else "対象",
            "" if field == "predicate" else "述語",
            SOURCE,
        )


def test_actual_is_detached_and_immutable() -> None:
    value = {"a": [1, False, None]}
    observation = PreconditionObservation(BINDING, cast(JsonValue, value))
    value["a"].append(4)
    assert observation.to_dict()["actual"] == {"a": [1, False, None]}
    with pytest.raises(TypeError):
        cast(dict[str, object], observation.actual)["a"] = 2


class Number(IntEnum):
    ONE = 1


@pytest.mark.parametrize("actual", [float("nan"), float("inf"), object(), {1: "a"}, Number.ONE])
def test_strict_json(actual: object) -> None:
    with pytest.raises(ValueError):
        PreconditionObservation(BINDING, cast(JsonValue, actual))


@pytest.mark.asyncio
async def test_normal_route_does_not_evaluate_predicate_or_copy_expected() -> None:
    owner = Owner()
    expected = PreconditionRef("条件A", "評価しない述語", "対象A", True)
    publication = await owner.router().read_current(BINDING)
    assert publication.value.actual is False
    assert publication.value.actual != expected.expected
    assert publication.tokens == (owner.participant.token(),)
    assert owner.calls == 1


def test_duplicate_registration() -> None:
    owner = Owner()
    registration = PreconditionSourceRegistration(SOURCE, owner, owner.participant)
    with pytest.raises(PreconditionReadError) as error:
        PreconditionSourceRouter((registration, registration))
    assert error.value.failure is PreconditionFailure.DUPLICATE_SOURCE


@pytest.mark.asyncio
async def test_unregistered_source() -> None:
    with pytest.raises(PreconditionReadError) as error:
        await PreconditionSourceRouter(()).read_current(BINDING)
    assert error.value.failure is PreconditionFailure.UNREGISTERED_SOURCE


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["precondition_id", "subject_ref", "predicate", "source"])
async def test_wrong_identity(field: str) -> None:
    owner = Owner()
    changed = PreconditionSourceBinding(
        "別" if field == "precondition_id" else BINDING.precondition_id,
        "別" if field == "subject_ref" else BINDING.subject_ref,
        "別" if field == "predicate" else BINDING.predicate,
        PreconditionSourceRef("別", "公開") if field == "source" else SOURCE,
    )
    owner.override = AuthorityReadPublication(
        PreconditionObservation(changed, False), (owner.participant.token(),)
    )
    with pytest.raises(PreconditionReadError) as error:
        await owner.router().read_current(BINDING)
    assert error.value.failure is PreconditionFailure.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_missing_token() -> None:
    owner = Owner()
    owner.override = AuthorityReadPublication(PreconditionObservation(BINDING, False), ())
    with pytest.raises(PreconditionReadError) as error:
        await owner.router().read_current(BINDING)
    assert error.value.failure is PreconditionFailure.INVALID_PUBLICATION


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_old_publication_after_noop_or_failed_mutation(failed: bool) -> None:
    owner = Owner()
    router = owner.router()
    old = await router.read_current(BINDING)
    try:
        with owner.participant.mutation():
            if failed:
                raise ValueError("試験用拒否")
    except ValueError:
        pass
    owner.override = old
    with pytest.raises(PreconditionReadError) as error:
        await router.read_current(BINDING)
    assert error.value.failure is PreconditionFailure.STALE_PUBLICATION
    owner.override = None
    assert (await router.read_current(BINDING)).tokens != old.tokens


@pytest.mark.asyncio
async def test_restart_cannot_relabel_old_instance() -> None:
    old_owner = Owner()
    old = await old_owner.router().read_current(BINDING)
    new_owner = Owner()
    new_owner.override = old
    with pytest.raises(PreconditionReadError) as error:
        await new_owner.router().read_current(BINDING)
    assert error.value.failure is PreconditionFailure.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_unused_owner_change_has_no_effect() -> None:
    owner, unrelated = Owner(), Owner()
    old = await owner.router().read_current(BINDING)
    with unrelated.participant.mutation():
        unrelated.actual = True
    owner.override = old
    assert await owner.router().read_current(BINDING) == old


@pytest.mark.asyncio
async def test_payload_bound() -> None:
    owner = Owner()
    with pytest.raises(PreconditionReadError) as error:
        await owner.router(max_publication_bytes=1).read_current(BINDING)
    assert error.value.failure is PreconditionFailure.CAPACITY_EXCEEDED


@pytest.mark.asyncio
async def test_cancellation_does_not_create_orphan() -> None:
    entered, cleaned = asyncio.Event(), asyncio.Event()

    class WaitingOwner(Owner):
        async def read_current(
            self, binding: PreconditionSourceBinding
        ) -> AuthorityReadPublication[PreconditionObservation]:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
            return await super().read_current(binding)

    owner = WaitingOwner()
    before = asyncio.all_tasks()
    task = asyncio.create_task(owner.router().read_current(BINDING))
    await entered.wait()
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
    assert asyncio.all_tasks() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exception", "not_async", "malformed", "retired", "forged_token"])
async def test_invalid_source_is_typed_failure(mode: str) -> None:
    class BadOwner(Owner):
        async def read_current(
            self, binding: PreconditionSourceBinding
        ) -> AuthorityReadPublication[PreconditionObservation]:
            if mode == "exception":
                raise ValueError("供給元の非公開詳細")
            return await super().read_current(binding)

    owner = BadOwner()
    router = owner.router()
    if mode == "not_async":
        owner.__dict__["read_current"] = lambda binding: None
    if mode == "malformed":
        owner.override = cast(AuthorityReadPublication[PreconditionObservation], object())
    if mode == "retired":
        owner.participant.retire()
    if mode == "forged_token":
        token = replace(owner.participant.token(), generation=999)
        owner.override = AuthorityReadPublication(PreconditionObservation(BINDING, False), (token,))
    with pytest.raises(PreconditionReadError) as error:
        await router.read_current(BINDING)
    assert "非公開詳細" not in str(error.value)


@pytest.mark.asyncio
async def test_mutation_while_reader_awaits_rejects_old_publication() -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedOwner(Owner):
        async def read_current(
            self, binding: PreconditionSourceBinding
        ) -> AuthorityReadPublication[PreconditionObservation]:
            publication = await super().read_current(binding)
            entered.set()
            await release.wait()
            return publication

    owner = DelayedOwner()
    task = asyncio.create_task(owner.router().read_current(BINDING))
    await entered.wait()
    with owner.participant.mutation():
        owner.actual = True
    release.set()
    with pytest.raises(PreconditionReadError) as error:
        await task
    assert error.value.failure is PreconditionFailure.STALE_PUBLICATION


@pytest.mark.asyncio
async def test_recancellation_drains_cleanup_and_suppressed_cancel() -> None:
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SuppressingOwner(Owner):
        async def read_current(
            self, binding: PreconditionSourceBinding
        ) -> AuthorityReadPublication[PreconditionObservation]:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup.set()
                await release.wait()
            return await super().read_current(binding)

    owner = SuppressingOwner()
    before = asyncio.all_tasks()
    task = asyncio.create_task(owner.router().read_current(BINDING))
    await entered.wait()
    task.cancel()
    await cleanup.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert asyncio.all_tasks() == before


def test_wrong_registered_owner_and_unsupported_participant() -> None:
    owner = Owner()
    with pytest.raises(PreconditionReadError) as error:
        PreconditionSourceRouter(
            (
                PreconditionSourceRegistration(
                    PreconditionSourceRef("別Owner", "公開"), owner, owner.participant
                ),
            )
        )
    assert error.value.failure is PreconditionFailure.IDENTITY_MISMATCH
    owner.participant.retire()
    with pytest.raises(PreconditionReadError) as error:
        owner.router()
    assert error.value.failure is PreconditionFailure.SOURCE_UNAVAILABLE


def test_registration_and_json_depth_bounds() -> None:
    owner = Owner()
    with pytest.raises(ValueError):
        owner.router(max_sources=True)
    value: object = None
    for _ in range(34):
        value = [value]
    with pytest.raises(PreconditionReadError) as error:
        PreconditionObservation(BINDING, cast(JsonValue, value))
    assert error.value.failure is PreconditionFailure.CAPACITY_EXCEEDED


@pytest.mark.asyncio
async def test_returned_tokens_remain_required_at_final_fence() -> None:
    from app.domain.contracts.finalization import AuthorityFinalizationFence, FinalizationFailure
    from tests.domain.contracts.test_finalization import Target

    owner = Owner()
    publication = await owner.router().read_current(BINDING)
    with owner.participant.mutation():
        owner.actual = True
    target = Target()
    result = AuthorityFinalizationFence().finalize(target.request(*publication.tokens))
    assert result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert target.calls == 0
