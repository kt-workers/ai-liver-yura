"""本番S2へ標準入力を安全に接続する薄い外側Adapter。"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.composition.cognition import CoreCognitionDelivery
from app.domain.brain_integration import BrainIntegrationRuntime, BrainIntegrationWorkOutcome
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.input_gateway import (
    InputAdmissionStatus,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSourceState,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ConsoleInputAdapter:
    """標準入力を正規Gatewayへ渡し、公開済み結果だけを表示する。"""

    delivery: CoreCognitionDelivery
    brain: BrainIntegrationRuntime
    bounds_policy: BrainOperationalBoundsPolicy
    source_context_revision: Callable[[], int]
    _normalizer: InputNormalizer = field(init=False, repr=False)
    _queue: asyncio.Queue[str | None] = field(init=False, repr=False)
    _trace_ids: set[str] = field(init=False, default_factory=set, repr=False)
    _reader_registered: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        self._normalizer = InputNormalizer(bounds_policy=self.bounds_policy)
        self._queue = asyncio.Queue()

    async def run(self, stop_requested: asyncio.Event) -> None:
        """受付と結果表示を別taskにし、前の処理完了を次の入力の前提にしない。"""
        loop = asyncio.get_running_loop()
        outcome_task = asyncio.create_task(self._observe_outcomes())
        self._register_reader(loop)
        print(
            "コンソール入力を受け付けます。EOF または SIGINT / SIGTERM で停止します。",
            flush=True,
        )
        try:
            while not stop_requested.is_set():
                line_task = asyncio.create_task(self._queue.get())
                stop_task = asyncio.create_task(stop_requested.wait())
                done, pending = await asyncio.wait(
                    (line_task, stop_task), return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if stop_task in done:
                    line_task.cancel()
                    await asyncio.gather(line_task, return_exceptions=True)
                    break
                line = line_task.result()
                if line is None:
                    print("標準入力が終了したため、停止します。", flush=True)
                    stop_requested.set()
                    break
                self._submit(line)
        finally:
            self._unregister_reader(loop)
            outcome_task.cancel()
            await asyncio.gather(outcome_task, return_exceptions=True)

    def _register_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            descriptor = sys.stdin.fileno()
        except (AttributeError, OSError):
            raise RuntimeError("標準入力を監視できません") from None
        loop.add_reader(descriptor, self._read_available)
        self._reader_registered = True

    def _unregister_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._reader_registered:
            try:
                loop.remove_reader(sys.stdin.fileno())
            finally:
                self._reader_registered = False

    def _read_available(self) -> None:
        line = sys.stdin.readline()
        self._queue.put_nowait(None if line == "" else line.rstrip("\n"))

    def _submit(self, text: str) -> None:
        if not text.strip():
            print("入力受付: REJECTED / 空の文章", flush=True)
            return
        trace_id = f"console-trace-{uuid.uuid4().hex}"
        observation = InputObservation(
            observation_id=f"console-input-{uuid.uuid4().hex}",
            source=InputSourceState(
                source_id="console",
                source_kind="console",
                availability=CapabilityAvailability.AVAILABLE,
                permission=InputPermission.GRANTED,
            ),
            modality=InputModality.TEXT,
            semantic_unit="user_text",
            observed_at=_now(),
            trace_id=trace_id,
            revisions=RevisionVector(self.source_context_revision()),
            payload={"text": text},
            correlation_id=trace_id,
        )
        admission = self._normalizer.normalize(observation)
        if admission.status is not InputAdmissionStatus.ACCEPTED:
            reason = admission.reason.value if admission.reason is not None else "unknown"
            print(f"入力受付: {admission.status.value} / {reason}", flush=True)
            return
        brain_admission = self.delivery.submit_input(admission, root_trigger_id=trace_id)
        self._trace_ids.add(trace_id)
        print(
            f"入力受付: accepted / Brain受付: {brain_admission.status.value} / trace: {trace_id}",
            flush=True,
        )

    async def _observe_outcomes(self) -> None:
        while True:
            outcome = await self.brain.next_outcome()
            if outcome.trace_id in self._trace_ids:
                self._display_outcome(outcome)

    def _display_outcome(self, outcome: BrainIntegrationWorkOutcome) -> None:
        failure = _failure_code(outcome)
        message = (
            f"trace: {outcome.trace_id} / module: {outcome.module.value}"
            f" / status: {outcome.status.value}"
        )
        if failure is not None:
            message += f" / failure: {failure}"
        trace = self.brain.trace(outcome.trace_id)
        if trace.decision_ids:
            message += f" / decisions: {','.join(trace.decision_ids)}"
        print(message, flush=True)


def _failure_code(outcome: BrainIntegrationWorkOutcome) -> str | None:
    if outcome.error is not None:
        return outcome.error
    result = outcome.result
    for field_name in ("role_failure", "boundary_failure", "failure"):
        failure = getattr(result, field_name, None)
        code = getattr(failure, "code", None)
        value = getattr(code, "value", None)
        if isinstance(value, str):
            return value
    return None
