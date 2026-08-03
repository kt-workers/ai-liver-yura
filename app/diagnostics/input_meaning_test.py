from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import TextIO, cast

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.behavior import BehaviorPlanningContext
from app.domain.cognitive_direction import StructuredInputMeaning
from app.domain.events import AgentEvent, AgentEventType
from app.ports.cognitive_direction import InputMeaningModel
from app.prompting import InputMeaningPromptBuilder
from app.runtime.cognitive_direction_services import InputMeaningInterpreter
from app.runtime.separated_situation_evaluator import (
    SeparatedSituationEvaluationAdapter,
)
from app.utils.trace import TraceLogger

_DEFAULT_OUTPUT_PATH = "logs/input_meaning_test.jsonl"


class _RecordingInputMeaningModel:
    """本番の意味解析Modelを変更せず、生レスポンスと例外だけを観測する。"""

    def __init__(self, delegate: InputMeaningModel) -> None:
        self._delegate = delegate
        self.raw_response: str | None = None
        self.prompt: str | None = None
        self.error: Exception | None = None

    def reset(self) -> None:
        self.raw_response = None
        self.prompt = None
        self.error = None

    async def interpret_input_meaning(self, activity: Activity) -> str:
        prompt = activity.context.get("plugin_prompt_override")
        self.prompt = prompt if isinstance(prompt, str) else None
        try:
            raw = await self._delegate.interpret_input_meaning(activity)
        except Exception as error:
            self.error = error
            raise
        self.raw_response = str(raw)
        return self.raw_response


class InputMeaningTestReporter:
    """意味解析LLMの入力・生出力・構造化結果をコンソールとJSONLへ出す。"""

    def __init__(
        self,
        output_path: str | Path | None = None,
        *,
        stream: TextIO | None = None,
        include_prompt: bool | None = None,
    ) -> None:
        configured_path = output_path or os.getenv(
            "YURA_INPUT_MEANING_TEST_LOG",
            _DEFAULT_OUTPUT_PATH,
        )
        self.output_path = Path(configured_path)
        self._stream = stream or sys.stdout
        self._include_prompt = (
            include_prompt
            if include_prompt is not None
            else _env_enabled("YURA_INPUT_MEANING_TEST_INCLUDE_PROMPT")
        )
        self._trace_logger = TraceLogger()

    def report(
        self,
        *,
        context: BehaviorPlanningContext,
        meaning: StructuredInputMeaning | None,
        raw_response: str | None,
        prompt: str | None,
        error: Exception | None,
        elapsed_ms: float,
    ) -> dict[str, object]:
        valid = meaning is not None
        error_type = type(error).__name__ if error is not None else None
        error_message = str(error) if error is not None else None
        if not valid and error_type is None:
            error_type = "schema_validation_failed"
            error_message = "InputMeaningJsonParserが構造化結果を受理しませんでした"

        record: dict[str, object] = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "source_event_id": context.source_event_id,
            "input": context.user_text,
            "valid": valid,
            "elapsed_ms": round(elapsed_ms, 3),
            "raw_response": raw_response,
            "parsed_response": meaning.as_context() if meaning is not None else None,
            "error_type": error_type,
            "error_message": error_message,
        }
        if self._include_prompt:
            record["prompt"] = prompt

        self._append_jsonl(record)
        self._print_record(record)
        self._trace_logger.info(
            "input_meaning_test:result",
            source_event_id=context.source_event_id,
            valid=valid,
            input_speech_act=(
                meaning.input_speech_act.value if meaning is not None else None
            ),
            expected_response=(
                meaning.expected_response.value if meaning is not None else None
            ),
            confidence=meaning.confidence if meaning is not None else None,
            elapsed_ms=round(elapsed_ms, 3),
            error_type=error_type,
            output_path=str(self.output_path),
        )
        return record

    def _append_jsonl(self, record: dict[str, object]) -> None:
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                )
                output.write("\n")
        except OSError as error:
            self._trace_logger.warning(
                "input_meaning_test:log_write_failed",
                output_path=str(self.output_path),
                error_type=type(error).__name__,
                error_message=str(error),
            )

    def _print_record(self, record: dict[str, object]) -> None:
        print("", file=self._stream)
        print("=" * 72, file=self._stream)
        print("意味解析LLM テスト結果", file=self._stream)
        print("=" * 72, file=self._stream)
        print(
            json.dumps(record, ensure_ascii=False, indent=2),
            file=self._stream,
        )
        print(f"JSONL: {self.output_path}", file=self._stream)
        self._stream.flush()


class InputMeaningTestRunner:
    """本番と同じ意味解析Serviceを実行し、Internal Directiveより前で停止する。"""

    def __init__(
        self,
        model: InputMeaningModel,
        *,
        reporter: InputMeaningTestReporter | None = None,
    ) -> None:
        self._recording_model = _RecordingInputMeaningModel(model)
        self._interpreter = InputMeaningInterpreter(
            self._recording_model,
            prompt_builder=InputMeaningPromptBuilder(),
        )
        self._situation_prompt_builder = SituationEvaluatorPromptBuilder()
        self._reporter = reporter or InputMeaningTestReporter()

    @property
    def output_path(self) -> Path:
        return self._reporter.output_path

    async def run(
        self,
        context: BehaviorPlanningContext,
    ) -> StructuredInputMeaning | None:
        """ユーザー入力を意味解析し、結果を記録してそのTurnを終了する。"""

        activity = self._build_situation_activity(context)
        planning_input = SeparatedSituationEvaluationAdapter._extract_planning_input(
            activity
        )
        self._recording_model.reset()
        started = perf_counter()
        meaning = await self._interpreter.interpret(activity, planning_input)
        elapsed_ms = (perf_counter() - started) * 1000.0
        self._reporter.report(
            context=context,
            meaning=meaning,
            raw_response=self._recording_model.raw_response,
            prompt=self._recording_model.prompt,
            error=self._recording_model.error,
            elapsed_ms=elapsed_ms,
        )
        return meaning

    def _build_situation_activity(
        self,
        context: BehaviorPlanningContext,
    ) -> Activity:
        """通常のSituation Evaluatorが意味解析前に作るActivityを再現する。"""

        prompt = self._situation_prompt_builder.build(context)
        return Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="ユーザー入力の状況と意味を構造化する",
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "situation_evaluator",
                "event_id": context.source_event_id,
                "user_input": context.user_text,
                "planner_state": {
                    "ongoing_activity_type": context.ongoing_activity_type,
                    "ongoing_activity": (
                        asdict(context.ongoing_activity)
                        if context.ongoing_activity is not None
                        else None
                    ),
                    "active_activity_definition": (
                        {
                            "activity_type": (
                                context.active_activity_definition.activity_type
                            ),
                            "supported_operations": [
                                operation.value
                                for operation in (
                                    context.active_activity_definition.supported_operations
                                )
                            ],
                        }
                        if context.active_activity_definition is not None
                        else None
                    ),
                    "drive": context.drive,
                    "emotion": context.emotion,
                    "last_activity_result": context.last_activity_result,
                },
                "constraints": [
                    "発話本文を生成しない",
                    "Capabilityの可用性や実行成功を判断しない",
                    "候補外のActivityを生成しない",
                ],
                "trace_context": context.trace_context,
                "llm_attempt": 1,
            },
            source_event_id=context.source_event_id,
        )


def install_input_meaning_test(
    runtime: object,
    *,
    reporter: InputMeaningTestReporter | None = None,
) -> InputMeaningTestRunner:
    """通常RuntimeのUSER_TEXT経路へ、意味解析後に消費する診断フックを付ける。

    APP_STARTEDなどUSER_TEXT以外のイベントは通常のBehavior Routingへ渡す。
    USER_TEXTは通常のIngress・履歴記録・Context構築を通した後、意味解析結果を
    記録して消費するため、Internal Directive・Activity・Character・TTSへ進まない。
    """

    coordinator = getattr(runtime, "_behavior_routing_coordinator", None)
    if coordinator is None:
        raise RuntimeError("BehaviorRoutingCoordinatorを取得できません")
    context_builder = getattr(coordinator, "_context_builder", None)
    if context_builder is None or not callable(getattr(context_builder, "build", None)):
        raise RuntimeError("BehaviorPlanningContextBuilderを取得できません")
    planner = getattr(coordinator, "_planner", None)
    evaluator = getattr(planner, "_situation_evaluator", None)
    model = getattr(evaluator, "_model", None)
    if model is None or not callable(getattr(model, "interpret_input_meaning", None)):
        raise RuntimeError("Input Meaning Interpreter用Modelを取得できません")

    original_route = getattr(coordinator, "route", None)
    if not callable(original_route):
        raise RuntimeError("Behavior Routingの通常経路を取得できません")

    runner = InputMeaningTestRunner(
        cast(InputMeaningModel, model),
        reporter=reporter,
    )
    trace_logger = TraceLogger()

    async def diagnostic_route(event: AgentEvent) -> AgentEvent | None:
        if event.event_type != AgentEventType.USER_TEXT:
            return await original_route(event)
        preparation = context_builder.build(event)
        await runner.run(preparation.context)
        trace_logger.info(
            "input_meaning_test:event_consumed",
            source_event_id=preparation.context.source_event_id,
            stop_stage="input_meaning_interpreter",
        )
        return None

    setattr(coordinator, "route", diagnostic_route)
    setattr(runtime, "_input_meaning_test_runner", runner)
    trace_logger.info(
        "input_meaning_test:installed",
        stop_stage="input_meaning_interpreter",
        output_path=str(runner.output_path),
    )
    return runner


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "on", "yes"}
