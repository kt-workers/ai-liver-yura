"""入力の採用結果と実所有者を、判断根拠の読取境界へ接続する。"""

from typing import Protocol

from app.composition.accepted_input import CoreAcceptedInputStore
from app.composition.appraisal import CoreAppraisalBinding
from app.composition.executive import CoreExecutiveEvidence
from app.domain.attention import AttentionSource, AttentionSourceKind
from app.domain.contracts.common import freeze_json
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveDecisionCandidate,
    ExecutiveFactKind,
    ExecutiveFactRef,
    ExecutiveSourceEvent,
    PreconditionFact,
)
from app.domain.plugin_registry.authority import PluginRegistryAuthority


class CoreExecutiveRequirementsReader(Protocol):
    """自己申告に依存しない上流方針と実前提条件を必須とする。"""

    async def preconditions_for(self, source: AttentionSource) -> tuple[PreconditionFact, ...]: ...

    async def requirements_for(
        self, candidate: ExecutiveDecisionCandidate
    ) -> tuple[AuthoritativeIntentRequirements, ...]: ...


class CoreExecutiveInputEvidenceReader:
    def __init__(
        self,
        inputs: CoreAcceptedInputStore,
        appraisal: CoreAppraisalBinding,
        registry: PluginRegistryAuthority,
        requirements: CoreExecutiveRequirementsReader,
    ) -> None:
        self._inputs = inputs
        self._appraisal = appraisal
        self._registry = registry
        self._requirements = requirements

    async def requirements_for(
        self, candidate: ExecutiveDecisionCandidate
    ) -> tuple[AuthoritativeIntentRequirements, ...]:
        return await self._requirements.requirements_for(candidate)

    async def read(self, source: AttentionSource) -> CoreExecutiveEvidence:
        preconditions = await self._requirements.preconditions_for(source)
        reference = self._appraisal.current_reference()
        revision = reference.context.source_context_revision
        if source.source_context_revision != revision:
            raise ValueError("選択された入力根拠の文脈が現在と一致しません")
        event_ids: tuple[str, ...]
        if source.kind is AttentionSourceKind.USER_INTERACTION:
            event_ids = (source.source_ref,)
        elif source.kind is AttentionSourceKind.APPRAISAL:
            commit = self._appraisal.current_commit()
            if (
                commit is None
                or commit.candidate.candidate_id != source.source_ref
                or commit.candidate.base_state_revision != source.source_revision
                or commit.candidate.source_context_revision != revision
            ):
                raise ValueError("選択された評価の確定根拠が現在と一致しません")
            event_ids = commit.candidate.source_event_ids
        else:
            raise ValueError("選択元に対応する入力根拠の供給元が未登録です")
        inputs = tuple(self._inputs.read(event_id, revision) for event_id in event_ids)
        if not inputs:
            raise ValueError("判断の契機に対応する入力根拠がありません")
        facts: dict[str, ExecutiveFactRef] = {}

        def add(value: ExecutiveFactRef) -> None:
            previous = facts.get(value.fact_id)
            if previous is not None and previous != value:
                raise ValueError("判断根拠の事実識別子が競合しています")
            facts[value.fact_id] = value

        goals = reference.goals
        for goal in (*goals.active_goals, *goals.suspended_goals, *goals.recently_changed_goals):
            add(
                ExecutiveFactRef(
                    goal.goal_id, ExecutiveFactKind.GOAL, goal.revision, freeze_json(goal.to_dict())
                )
            )
        for commitment in (*goals.commitments, *goals.recently_changed_commitments):
            add(
                ExecutiveFactRef(
                    commitment.commitment_id,
                    ExecutiveFactKind.COMMITMENT,
                    commitment.revision,
                    freeze_json(commitment.to_dict()),
                )
            )
        for activity in reference.activities:
            command_id = activity.invocation.command.command_id
            add(
                ExecutiveFactRef(
                    command_id,
                    ExecutiveFactKind.ACTIVITY,
                    activity.record_revision,
                    freeze_json(
                        {
                            "command_id": command_id,
                            "status": activity.result.status.value,
                            "effect_uncertainty": activity.effect_uncertainty.value,
                        }
                    ),
                )
            )
        return CoreExecutiveEvidence(
            source=source,
            source_events=tuple(
                ExecutiveSourceEvent(
                    item.event.envelope.event_id, item.event.envelope.occurred_at, True
                )
                for item in inputs
            ),
            meaning=inputs[0].result.meaning if len(inputs) == 1 else None,
            facts=tuple(facts.values()),
            capabilities=self._registry.capability_descriptors(),
            preconditions=preconditions,
        )
