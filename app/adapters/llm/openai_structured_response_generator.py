from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping

from app.adapters.llm.openai_response_generator import OpenAIResponseGenerator
from app.domain.activities import Activity
from app.ports.structured_output import (
    StructuredOutputContract,
    StructuredOutputGenerationError,
)
from app.utils.async_blocking import run_cancellable_blocking
from app.utils.llm_trace import build_llm_trace_context


_ALLOWED_REASONING_EFFORT = frozenset({"none", "low", "medium", "high", "xhigh"})


class OpenAIStructuredResponseGenerator(OpenAIResponseGenerator):
    """既存text Adapterを壊さずschema-critical roleだけStructured Outputsへ接続する。"""

    async def generate_structured_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        prompt = self._prompt_builder.build_prompt(
            character_profile=self._character_profile,
            activity=activity,
        )
        reasoning_effort = self._reasoning_effort(activity)
        trace_context = build_llm_trace_context(activity)
        request_input = self._structured_request_payload(
            prompt,
            contract,
            reasoning_effort=reasoning_effort,
        )
        self._trace_logger.llm_request(
            purpose=trace_context.purpose,
            provider="openai",
            model=self._model,
            activity_id=trace_context.activity_id,
            event_id=trace_context.event_id,
            session_id=trace_context.session_id,
            request=request_input,
            user_input=trace_context.user_input,
            available_capabilities=trace_context.available_capabilities,
            planner_state=trace_context.planner_state,
            constraints=trace_context.constraints,
            llm_role=trace_context.llm_role,
            model_key=trace_context.model_key or self._model,
            service=trace_context.service or "openai_responses_structured",
            request_id=trace_context.request_id,
            attempt=trace_context.attempt,
            **trace_context.trace_context.as_log_fields(),
        )
        result = await run_cancellable_blocking(
            self._generate_structured_sync,
            prompt,
            contract,
            reasoning_effort,
        )
        self._trace_logger.llm_response(
            purpose=trace_context.purpose,
            provider="openai",
            model=self._model,
            activity_id=trace_context.activity_id,
            parsed_response=dict(result),
            adopted_text=json.dumps(result, ensure_ascii=False),
            fallback_used=False,
            stage="structured_adopted",
            llm_role=trace_context.llm_role,
            model_key=trace_context.model_key or self._model,
            service=trace_context.service or "openai_responses_structured",
            request_id=trace_context.request_id,
            attempt=trace_context.attempt,
            **trace_context.trace_context.as_log_fields(),
        )
        return result

    def _structured_request_payload(
        self,
        prompt: str,
        contract: StructuredOutputContract,
        *,
        reasoning_effort: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": contract.name,
                    "schema": dict(contract.schema),
                    "strict": contract.strict,
                }
            },
        }
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        return payload

    def _generate_structured_sync(
        self,
        prompt: str,
        contract: StructuredOutputContract,
        reasoning_effort: str | None,
    ) -> Mapping[str, object]:
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise StructuredOutputGenerationError(
                f"{self._api_key_env} is required for structured output"
            )

        request_body = json.dumps(
            self._structured_request_payload(
                prompt,
                contract,
                reasoning_effort=reasoning_effort,
            )
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url.rstrip('/')}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                response_body = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as error:
            raise StructuredOutputGenerationError(
                f"OpenAI structured output request failed: {type(error).__name__}"
            ) from error

        try:
            response_json = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise StructuredOutputGenerationError(
                "OpenAI structured output response was not valid JSON"
            ) from error

        status = response_json.get("status")
        if status is not None and status != "completed":
            raise StructuredOutputGenerationError(
                f"OpenAI structured output response status is {status!r}"
            )

        generated_text = self._extract_output_text(response_json).strip()
        if not generated_text:
            raise StructuredOutputGenerationError(
                "OpenAI structured output response contained no output text"
            )
        try:
            payload = json.loads(generated_text)
        except json.JSONDecodeError as error:
            raise StructuredOutputGenerationError(
                "OpenAI structured output text was not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise StructuredOutputGenerationError(
                "OpenAI structured output root must be an object"
            )
        return dict(payload)

    @staticmethod
    def _reasoning_effort(activity: Activity) -> str | None:
        value = activity.context.get("reasoning_effort")
        if value is None:
            return None
        if not isinstance(value, str) or value not in _ALLOWED_REASONING_EFFORT:
            raise StructuredOutputGenerationError(
                "unsupported structured output reasoning_effort"
            )
        return value
