from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from app.core.plugins import PluginManager
from app.core.plugins.user_request import interpret_user_request
from app.domain.activities import ActivityType, OngoingActivity
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    OngoingActivityPlanningContext,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_registry import ActivityRegistry
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.motivation_appraiser import MotivationAppraiser
from app.runtime.response_content_planner import ResponseContentPlanner


@dataclass(frozen=True, slots=True)
class BehaviorPlanningPreparation:
    event: AgentEvent
    context: BehaviorPlanningContext
    ongoing_activity: OngoingActivity | None


class BehaviorPlanningContextBuilder:
    """Behavior Plannerへ渡す状態・記憶・Activity定義を組み立てる。"""

    def __init__(
        self,
        *,
        activity_manager: ActivityManager,
        agent_life_service: AgentLifeService,
        plugin_manager: PluginManager,
        activity_registry: ActivityRegistry | None = None,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        motivation_appraiser: MotivationAppraiser | None = None,
        response_content_planner: ResponseContentPlanner | None = None,
    ) -> None:
        self._activity_manager = activity_manager
        self._agent_life_service = agent_life_service
        self._plugin_manager = plugin_manager
        self._activity_registry = activity_registry
        self._short_term_memory = short_term_memory
        self._topic_history = topic_history
        self._motivation_appraiser = motivation_appraiser or MotivationAppraiser()
        self._response_content_planner = (
            response_content_planner or ResponseContentPlanner()
        )

    def build(self, event: AgentEvent) -> BehaviorPlanningPreparation:
        agent_state = self._agent_life_service.agent_state
        ongoing = self._activity_manager.ongoing_activity
        relationship = self._agent_life_service.preview_relationship(event)
        relationship_context = (
            relationship.as_context() if relationship is not None else {}
        )
        moral_context = {
            "profile": agent_state.moral_profile.as_dict(),
            "state": agent_state.current_moral.as_dict(),
            "composite": agent_state.moral_profile.compose(
                agent_state.current_moral
            ).as_dict(),
            "observation_only": True,
        }
        motivation_context = self._motivation_appraiser.appraise(
            agent_state.current_desire,
            relationship,
            moral_profile=agent_state.moral_profile,
            moral_state=agent_state.current_moral,
        ).as_context()
        situation_context = agent_state.current_situation.as_context()
        memory_context = agent_state.memory.as_context()
        response_content_plan = self._response_content_planner.build(
            motivation=motivation_context,
            moral=moral_context,
        )
        response_memory_context = {
            **memory_context,
            "response_content_plan": response_content_plan.as_context(),
        }
        conversation_history = self._conversation_history()
        related_knowledge = self._related_knowledge(memory_context)
        enriched_event = replace(
            event,
            payload={
                **event.payload,
                "input_authority": {
                    "role": event.authority.role,
                    "instruction_trusted": event.authority.instruction_trusted,
                },
                "relationship": relationship_context,
                "motivation": motivation_context,
                "moral": moral_context,
                "situation": situation_context,
                "memory": response_memory_context,
                "emotion": asdict(agent_state.current_emotion),
                "drive": asdict(agent_state.current_drive),
                "conversation_history": conversation_history,
                "related_knowledge": related_knowledge,
            },
        )
        definitions = (
            self._activity_registry.list_definitions()
            if self._activity_registry is not None
            else self._plugin_manager.list_activity_definitions()
        )
        if event.event_type == AgentEventType.APP_STARTED:
            definitions = (self.startup_activity_definition(),)
        text = str(enriched_event.payload.get("text") or "")
        planning_context = BehaviorPlanningContext(
            user_text=text,
            source_event_id=enriched_event.event_id,
            available_capabilities=self._plugin_manager.list_capabilities(),
            event_type=enriched_event.event_type.value,
            request_kind=(
                interpret_user_request(text).kind.value
                if enriched_event.event_type == AgentEventType.USER_TEXT
                else None
            ),
            authority_role=enriched_event.authority.role,
            instruction_trusted=enriched_event.authority.instruction_trusted,
            activity_definitions=definitions,
            active_activity_definition=(
                self._plugin_manager.active_activity_definition()
            ),
            ongoing_activity_type=(
                ongoing.activity_type if ongoing is not None else None
            ),
            ongoing_activity=self.ongoing_planning_context(ongoing),
            drive=asdict(agent_state.current_drive),
            emotion=asdict(agent_state.current_emotion),
            relationship=relationship_context,
            motivation=motivation_context,
            moral=moral_context,
            situation=situation_context,
            memory=memory_context,
            conversation_history=conversation_history,
            related_knowledge=related_knowledge,
            last_activity_result=self._activity_manager.last_activity_result,
            trace_context=enriched_event.trace_context,
        )
        return BehaviorPlanningPreparation(
            event=enriched_event,
            context=planning_context,
            ongoing_activity=ongoing,
        )

    def _conversation_history(self) -> tuple[dict[str, object], ...]:
        if self._short_term_memory is None:
            return ()
        return tuple(
            {
                "role": item.role,
                "text": item.text,
                "counterpart_id": item.counterpart_id,
                "display_name": item.display_name,
                "created_at": (
                    item.created_at.isoformat() if item.created_at is not None else None
                ),
            }
            for item in self._short_term_memory.recent_conversation(limit=6)
        )

    def _related_knowledge(
        self, memory_context: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        knowledge: list[dict[str, object]] = []
        semantic_facts = memory_context.get("semantic_facts")
        if isinstance(semantic_facts, list):
            knowledge.extend(
                dict(item) for item in semantic_facts if isinstance(item, dict)
            )
        if self._topic_history is not None:
            knowledge.extend(
                {
                    "category": item.category.value,
                    "summary": item.summary,
                    "source_text": item.source_text,
                    "activity_type": item.activity_type,
                }
                for item in self._topic_history.recent_entries(limit=5)
            )
        return tuple(knowledge)

    @staticmethod
    def startup_activity_definition() -> ActivityDefinition:
        return ActivityDefinition(
            activity_type=ActivityType.AWAKENING.value,
            display_name="覚醒と状況認識",
            required_capability=None,
            provider_plugin_id="runtime",
            description="起動後の状態を整え、発話せずに周囲を認識する",
            supported_operations=(ActivityOperation.START,),
            constraints_schema={"type": "object", "additionalProperties": True},
        )

    @staticmethod
    def ongoing_planning_context(
        ongoing: OngoingActivity | None,
    ) -> OngoingActivityPlanningContext | None:
        if ongoing is None:
            return None
        summary_keys = (
            "plugin_id",
            "capability",
            "plugin_session_id",
            "plugin_state_version",
            "plugin_activity_status",
        )
        constraints = ongoing.context.get("constraints")
        recent_turns: tuple[dict[str, object], ...] = tuple(
            {
                "turn_id": turn.turn_id,
                "sequence": turn.sequence,
                "operation": turn.operation,
                "input": turn.input_text,
                "execution_status": (
                    turn.execution_result.status.value
                    if turn.execution_result is not None
                    else None
                ),
            }
            for turn in ongoing.turns[-3:]
        )
        return OngoingActivityPlanningContext(
            ongoing_activity_id=ongoing.ongoing_activity_id,
            activity_type=ongoing.activity_type,
            status=ongoing.status.value,
            goal=ongoing.goal,
            constraints=dict(constraints) if isinstance(constraints, dict) else {},
            expected_input=ongoing.expected_input,
            turn_count=len(ongoing.turns),
            current_operation=ongoing.turns[-1].operation if ongoing.turns else None,
            plugin_state_summary={
                key: ongoing.context[key]
                for key in summary_keys
                if key in ongoing.context
            },
            recent_turns=recent_turns,
        )
