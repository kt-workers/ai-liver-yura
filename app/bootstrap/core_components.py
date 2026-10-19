"""本体の構成要素を組み立てる。起動・停止の実行状態は所有しない。"""

from __future__ import annotations

from dataclasses import dataclass

from app.bootstrap.cognition_configuration import CoreCognitionConfiguration
from app.config.core import CoreConfig
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.goals import GoalCommitmentStore
from app.infrastructure.scheduling import RuntimeClock, SystemRuntimeClock
from app.usecases.accepted_inputs import CoreAcceptedInputStore
from app.usecases.brain_input_meaning import InputMeaningBrainModulePort
from app.usecases.brain_integration_runtime import BrainIntegrationRuntime
from app.usecases.cognition_delivery import CoreCognitionDelivery
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.input_meaning import InputMeaningInterpreter
from app.usecases.input_reference_context import CoreInputReferenceContextBinding
from app.usecases.lifecycle import ApplicationLifecycle
from app.usecases.memory_persistence import CoreMemoryPersistenceBinding
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class CoreComponents:
    """構成済みの値とPort。起動・停止の状態は保持しない。"""

    config: CoreConfig
    character_definition: CharacterDefinitionDocument
    lifecycle: ApplicationLifecycle
    brain: BrainIntegrationRuntime
    interpreter: InputMeaningInterpreter
    bridge: InputMeaningBrainModulePort
    llm: LLMRolePort
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding
    activities: ActivityExecutionAuthority
    input_context: CoreInputReferenceContextBinding
    runtime_subject_identity: RuntimeSubjectIdentity
    memory: CoreMemoryPersistenceBinding | None = None
    cognition: CoreCognitionDelivery | None = None


def compose_core_components(
    config: CoreConfig,
    character: CharacterDefinitionDocument,
    llm: LLMRolePort,
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding,
    memory: CoreMemoryPersistenceBinding | None = None,
    lifecycle: ApplicationLifecycle | None = None,
    cognition: CoreCognitionConfiguration | None = None,
    *,
    prepared_activities: ActivityExecutionAuthority | None = None,
    prepared_context: CoreInputReferenceContextBinding | None = None,
    prepared_clock: RuntimeClock | None = None,
) -> CoreComponents:
    from app.domain.activity_execution.speech_observation import SPEECH_OBSERVATION_POLICY

    if cognition is None:
        raise ValueError("統合本体には認知・主観評価・注意・判断の構成が必須です")
    activities = (
        prepared_activities
        if prepared_activities is not None
        else (
            ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
            if cognition.speech is not None
            else ActivityExecutionAuthority()
        )
    )
    input_context = (
        prepared_context
        if prepared_context is not None
        else CoreInputReferenceContextBinding(
            goals, activities, config.input_meaning_policy, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    )
    interpreter = InputMeaningInterpreter(
        llm,
        input_context,
        config.input_meaning_policy,
    )
    bridge = InputMeaningBrainModulePort(
        interpreter,
        CoreAcceptedInputStore(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_source_event_refs),
    )
    clock = prepared_clock if prepared_clock is not None else SystemRuntimeClock()
    lifecycle = (
        lifecycle if lifecycle is not None else ApplicationLifecycle(clock, config.shutdown_policy)
    )
    brain = BrainIntegrationRuntime(clock, config.integration_policy)
    assert bridge.inputs is not None
    delivery = cognition.compose(
        brain, input_context, bridge.inputs, llm, clock, memory, goals
    )
    delivery.register(bridge)
    return CoreComponents(
        config,
        character,
        lifecycle,
        brain,
        interpreter,
        bridge,
        llm,
        goals,
        activities,
        input_context,
        RuntimeSubjectIdentity(
            self_subject_ref=character.character_id,
            character_id=character.character_id,
            character_schema_version=character.schema_version,
            character_definition_revision=character.definition_revision,
        ),
        memory,
        delivery,
    )
