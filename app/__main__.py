from __future__ import annotations

import asyncio
import os
from typing import Protocol

from app.adapters.input import (
    ConsoleInputReceiver,
    WebInputReceiver,
    WebInputReceiverConfig,
)
from app.bootstrap.awakening_runtime_setup import (
    build_awakening_capabilities,
    create_awakening_context_service_from_env,
)
from app.bootstrap.body_runtime_setup import (
    clear_bound_body_runtime,
    create_bound_body_runtime_from_env,
    install_body_aware_runtime_components,
)
from app.bootstrap.runtime import create_runtime_coordinator
from app.bootstrap.runtime_preflight import validate_runtime_service_settings
from app.config.app_config import load_app_config
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.integrations.streaming import create_core_streaming_integration
from app.utils.trace import TraceLogger


class _StoppableReceiver(Protocol):
    async def wait_until_stopped(self) -> None: ...


def should_start_console_input(_runtime_mode: str) -> bool:
    """The core process always exposes its trusted local operator input."""

    return True


def is_demo_exit_command(value: str) -> bool:
    """Compatibility helper for callers that still provide a terminal loop."""

    return value.strip().lower() in {"exit", "quit"}


def is_web_conversation_enabled() -> bool:
    return (
        os.getenv("YURA_WEB_CONVERSATION_ENABLED", "1").strip().lower()
        not in {"0", "false", "off"}
    )


async def _wait_until_shutdown(receiver: _StoppableReceiver) -> bool:
    """Return whether the top-level wait was canceled by an external shutdown."""

    try:
        await receiver.wait_until_stopped()
    except asyncio.CancelledError:
        return True
    return False


async def _await_runtime_shutdown(runtime_task: asyncio.Task[None]) -> bool:
    """Collect an already-stopping runtime task without leaking cancellation."""

    try:
        await runtime_task
    except asyncio.CancelledError:
        return True
    return False


async def async_main() -> None:
    """Run Yura's core without composing OBS or YouTube operations."""

    config = load_app_config()
    validate_runtime_service_settings(config)
    TraceLogger.configure(
        level=config.trace.level,
        trace_file_path=config.trace.file_path,
        output_format=config.trace.format,
        max_bytes=config.trace.max_bytes,
        backup_count=config.trace.backup_count,
        timezone_name=config.trace.timezone,
        debug_file_enabled=config.trace.debug_file_enabled,
        debug_file_path=config.trace.debug_file_path,
        log_llm_prompts=config.trace.log_llm_prompts,
        log_llm_responses=config.trace.log_llm_responses,
        log_user_input=config.trace.log_user_input,
    )
    trace_logger = TraceLogger()
    trace_logger.info(
        "app:start",
        app_name=config.app.name,
        app_mode=config.app.mode,
        response_generator_type=config.response_generator.type,
    )
    web_conversation_enabled = is_web_conversation_enabled()
    install_body_aware_runtime_components()
    runtime = create_runtime_coordinator(
        config,
        web_conversation_enabled=web_conversation_enabled,
    )
    body_runtime = create_bound_body_runtime_from_env()
    if body_runtime is not None:
        await body_runtime.start()

    awakening_service = create_awakening_context_service_from_env()
    awakening_context = awakening_service.begin(
        build_awakening_capabilities(
            body_available=body_runtime is not None,
            tts_available=config.speech.enabled,
            conversation_output_available=True,
        )
    )

    streaming_integration = create_core_streaming_integration(runtime.publish_event)
    receiver = (
        WebInputReceiver(
            WebInputReceiverConfig(
                host=os.getenv("YURA_WEB_INPUT_HOST", "127.0.0.1"),
                port=int(os.getenv("YURA_WEB_INPUT_PORT", "8771")),
            )
        )
        if web_conversation_enabled
        else ConsoleInputReceiver()
    )
    runtime_task = asyncio.create_task(runtime.run())
    await streaming_integration.start()

    await runtime.publish_event(
        AgentEvent(
            event_type=AgentEventType.APP_STARTED,
            payload={
                "source": "app_main",
                "awakening_context": awakening_context.as_context(),
            },
            priority=20,
            discardable=False,
            authority=InputAuthority.SYSTEM,
        )
    )

    async def route_console_event(event: AgentEvent) -> None:
        if event.event_type == AgentEventType.USER_TEXT:
            await runtime.submit_user_text(
                str(event.payload.get("text") or ""),
                source=str(event.payload.get("source") or "external"),
                authority=event.authority,
            )
            return
        await runtime.publish_event(event)

    if web_conversation_enabled:
        print("ゆらを起動しました。Web会話画面から話しかけてください。終了: Ctrl-C")
    else:
        print("ゆらを起動しました。管理者として自然文で指示できます。終了: exit / quit")
    interrupted = False
    runtime_task_cancelled = False
    try:
        await receiver.start(route_console_event)
        interrupted = await _wait_until_shutdown(receiver)
        if interrupted:
            trace_logger.info("app:interrupt_received", signal="cancelled")
    finally:
        await receiver.stop()
        await streaming_integration.close()
        if body_runtime is not None:
            await body_runtime.stop()
        clear_bound_body_runtime()
        runtime.stop()
        awakening_service.save_shutdown_snapshot(runtime.agent_state)
        runtime_task_cancelled = await _await_runtime_shutdown(runtime_task)
        trace_logger.info(
            "app:finished",
            interrupted=interrupted,
            runtime_task_cancelled=runtime_task_cancelled,
        )
        print("終了しました。")


def main() -> None:
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()
