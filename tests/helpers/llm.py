from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)


def make_execution_policy(
    model_class: LLMModelClass,
    reasoning_effort: LLMReasoningEffort,
    timeout_seconds: float,
    max_attempts: int,
    max_output_tokens: int,
    temperature: float | None = None,
) -> LLMExecutionPolicy:
    return LLMExecutionPolicy(
        "test.llm.execution",
        1,
        model_class,
        reasoning_effort,
        timeout_seconds,
        max_attempts,
        max_output_tokens,
        LLMRequestRetryPolicy(0.01, 1.0, 0.01),
        temperature_normalized=temperature,
    )
