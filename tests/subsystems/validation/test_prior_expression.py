"""採用済み表現だけを本番の履歴入力へ渡し、意味検証を維持する。"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.semantic_verification import (
    BlindInteractionAct,
    SemanticVerificationAuthority,
    SpeechActBudgetObservation,
)
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import RunContext
from app.subsystems.validation.speech_adjacent import SpeechPriorExample
from tests.domain.character_language import test_character_language as character
from tests.domain.semantic_verification import test_semantic_verification as semantic
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_speech_adjacent import (
    CharacterPort,
    Connections,
    case,
    spec,
)


def example(*, rejected: bool = False) -> SpeechPriorExample:
    snapshot = semantic._snapshot()
    owner = SemanticVerificationAuthority()
    blind = owner.commit_blind(
        semantic._blind_candidate(
            snapshot,
            units=(semantic._unit(acts=(BlindInteractionAct.DIRECTED_QUESTION,)),)
            if rejected
            else None,
        ),
        snapshot,
        observation_id="prior-blind",
        committed_at=semantic.NOW + timedelta(seconds=2),
    )
    relation = owner.commit_relation(
        semantic._relation_candidate(
            snapshot,
            blind.observation_id,
            budget=SpeechActBudgetObservation(1, 0) if rejected else None,
        ),
        snapshot,
        blind,
        observation_id="prior-relation",
        committed_at=semantic.NOW + timedelta(seconds=3),
    )
    _, acceptance = owner.reconcile(
        snapshot,
        blind,
        relation,
        observation_id="prior-observation",
        acceptance_id="prior-acceptance",
        committed_at=semantic.NOW + timedelta(seconds=3),
    )
    return SpeechPriorExample(snapshot.utterance, acceptance, ())


class RecordingConnections(Connections):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[CharacterLanguageContextSnapshot] = []
        self.requests: list[LLMRoleRequest] = []

    def realizer(
        self, context: RunContext, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageRealizer:
        self.inputs.append(snapshot)
        requests = self.requests

        class Port(CharacterPort):
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                requests.append(request)
                return await super().invoke(request)

        return CharacterLanguageRealizer(
            Port(snapshot),
            character._LiveState(character.current(snapshot)),
            CharacterLanguageAuthority(),
            character.policy(),
        )


@pytest.mark.asyncio
async def test_accepted_prior_reaches_realizer_and_new_output_still_undergoes_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = example()
    item = case()
    item = replace(
        item,
        character_context=replace(
            item.character_context, captured_at=prior.acceptance.committed_at
        ),
        prior_examples=(prior,),
    )
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    monkeypatch.setattr(semantic, "NOW", prior.acceptance.committed_at + timedelta(seconds=1))
    item = replace(item, created_at=semantic.NOW)
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    connections = RecordingConnections()
    result = await connections.runner(item).run(spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert (
        connections.inputs[0].prior_realizations[0].source_utterance_id
        == prior.utterance.utterance_id
    )
    assert len(connections.snapshots) == 1
    prior_input = value_at(connections.requests[0].input.value, "prior_realizations", 0)
    assert isinstance(prior_input, Mapping)
    assert set(prior_input) == {"source_utterance_id", "text", "committed_at"}
    assert value_at(prior_input, "source_utterance_id") == prior.utterance.utterance_id
    assert (
        value_at(result.stage_results[0].typed_outputs, "verification", "acceptance", "state")
        == "accepted"
    )
    assert value_at(result.stage_results[0].typed_outputs, "prior_utterance_ids") == (
        prior.utterance.utterance_id,
    )


@pytest.mark.asyncio
async def test_future_acceptance_is_rejected_before_any_provider_call() -> None:
    item = replace(case(), prior_examples=(example(),))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    connections = RecordingConnections()
    result = await connections.runner(item).run(spec(), item.fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert not connections.inputs


@pytest.mark.asyncio
async def test_rejected_prior_is_excluded_from_generation_input() -> None:
    prior = example(rejected=True)
    item = replace(case(), prior_examples=(prior,))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    connections = RecordingConnections()
    result = await connections.runner(item).run(spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert connections.inputs[0].prior_realizations == ()
    assert value_at(connections.requests[0].input.value, "prior_realizations") == ()


@pytest.mark.asyncio
async def test_old_character_definition_is_rejected_before_generation() -> None:
    prior = example()
    item = case()
    snapshot = replace(
        item.character_context,
        captured_at=prior.acceptance.committed_at,
        character_profile=replace(item.character_context.character_profile, definition_revision=2),
    )
    item = replace(item, character_context=snapshot, prior_examples=(prior,))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    connections = RecordingConnections()
    result = await connections.runner(item).run(spec(), item.fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert not connections.requests and not connections.inputs


@pytest.mark.asyncio
async def test_prior_without_acceptance_cannot_bypass_selection_via_snapshot() -> None:
    from app.domain.character_language import prior_realization_from_utterance

    prior = example()
    item = case()
    snapshot = replace(
        item.character_context,
        captured_at=prior.acceptance.committed_at,
        prior_realizations=(prior_realization_from_utterance(prior.utterance, ()),),
    )
    item = replace(item, character_context=snapshot)
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    connections = RecordingConnections()
    result = await connections.runner(item).run(spec(), item.fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert not connections.requests
