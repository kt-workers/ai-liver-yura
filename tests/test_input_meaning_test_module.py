from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from app.diagnostics.input_meaning_test import (
    InputMeaningTestReporter,
    InputMeaningTestRunner,
    install_input_meaning_test,
)
from app.domain.behavior import BehaviorPlanningContext
from app.domain.events import AgentEvent, AgentEventType


class StubInputMeaningModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.activities = []

    async def interpret_input_meaning(self, activity):
        self.activities.append(activity)
        return self.response


class StubContextBuilder:
    def __init__(self, context: BehaviorPlanningContext) -> None:
        self.context = context
        self.events: list[AgentEvent] = []

    def build(self, event: AgentEvent):
        self.events.append(event)
        return SimpleNamespace(event=event, context=self.context)


class StubCoordinator:
    def __init__(
        self,
        model: StubInputMeaningModel,
        context_builder: StubContextBuilder,
    ) -> None:
        self._context_builder = context_builder
        self._planner = SimpleNamespace(
            _situation_evaluator=SimpleNamespace(_model=model)
        )
        self.normal_events: list[AgentEvent] = []

    async def route(self, event: AgentEvent) -> AgentEvent:
        self.normal_events.append(event)
        return event


class StubRuntime:
    def __init__(self, coordinator: StubCoordinator) -> None:
        self._behavior_routing_coordinator = coordinator


def meaning_json() -> str:
    return json.dumps(
        {
            "input_speech_act": "question",
            "primary_intent": "ask_agent_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "agent_internal_state", "id": "current_desire"},
            "entities": [],
            "references": [],
            "information_provided": [],
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "conversation_phase_signal": "continue",
            "confidence": 0.96,
            "reason": "direct question about current desire",
        },
        ensure_ascii=False,
    )


def planning_context(text: str = "今は何をしたい気分ですか？") -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text=text,
        source_event_id="event-meaning-test",
        available_capabilities=frozenset(),
        emotion={"joy": 0.2},
        drive={"curiosity": 0.7},
        situation={"current_topic": "現在の気分"},
        conversation_history=(
            {"role": "assistant", "text": "今日は静かだね"},
        ),
    )


@pytest.mark.asyncio
async def test_runner_uses_production_prompt_and_records_raw_and_parsed_output(
    tmp_path,
) -> None:
    model = StubInputMeaningModel(meaning_json())
    stream = io.StringIO()
    output_path = tmp_path / "input_meaning.jsonl"
    reporter = InputMeaningTestReporter(
        output_path,
        stream=stream,
        include_prompt=True,
    )
    runner = InputMeaningTestRunner(model, reporter=reporter)

    meaning = await runner.run(planning_context())

    assert meaning is not None
    assert meaning.input_speech_act.value == "question"
    assert meaning.expected_response.value == "direct_answer"
    assert len(model.activities) == 1
    request = model.activities[0]
    assert request.context["llm_role"] == "input_meaning_interpreter"
    assert "# ObservedInput" in request.context["plugin_prompt_override"]
    assert "Internal Directive" not in request.context["plugin_prompt_override"]

    records = output_path.read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record["valid"] is True
    assert record["raw_response"] == meaning_json()
    assert record["parsed_response"]["input_speech_act"] == "question"
    assert "prompt" in record
    assert "意味解析LLM テスト結果" in stream.getvalue()


@pytest.mark.asyncio
async def test_runner_records_schema_failure_without_calling_later_roles(
    tmp_path,
) -> None:
    model = StubInputMeaningModel("not-json")
    output_path = tmp_path / "invalid.jsonl"
    runner = InputMeaningTestRunner(
        model,
        reporter=InputMeaningTestReporter(
            output_path,
            stream=io.StringIO(),
        ),
    )

    meaning = await runner.run(planning_context("あいうえお"))

    assert meaning is None
    assert len(model.activities) == 1
    record = json.loads(output_path.read_text(encoding="utf-8"))
    assert record["valid"] is False
    assert record["error_type"] == "schema_validation_failed"
    assert record["parsed_response"] is None


@pytest.mark.asyncio
async def test_installed_route_consumes_user_text_and_delegates_other_events(
    tmp_path,
) -> None:
    model = StubInputMeaningModel(meaning_json())
    context = planning_context()
    context_builder = StubContextBuilder(context)
    coordinator = StubCoordinator(model, context_builder)
    runtime = StubRuntime(coordinator)
    reporter = InputMeaningTestReporter(
        tmp_path / "installed.jsonl",
        stream=io.StringIO(),
    )

    install_input_meaning_test(runtime, reporter=reporter)

    user_event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": context.user_text},
    )
    assert await coordinator.route(user_event) is None
    assert len(model.activities) == 1
    assert coordinator.normal_events == []

    app_started = AgentEvent(
        event_type=AgentEventType.APP_STARTED,
        payload={"source": "test"},
    )
    assert await coordinator.route(app_started) is app_started
    assert coordinator.normal_events == [app_started]
