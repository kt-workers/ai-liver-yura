"""既存Adapter意味試験だけの局所Session。production process保証には使用しない。"""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.domain.speech_runtime.contracts import SpeechPresentationCommand, SpeechPresentationReport
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy
from app.domain.speech_runtime.presentation import PresentationAdapter


@runtime_checkable
class _Closable(Protocol):
    async def aclose(self) -> None: ...


class LocalPresentationSession:
    def __init__(self, iterator: AsyncIterator[SpeechPresentationReport]) -> None:
        self.iterator = iterator

    async def receive(self) -> SpeechPresentationReport:
        return await anext(self.iterator)

    async def close(self) -> None:
        if isinstance(self.iterator, _Closable):
            await self.iterator.aclose()


class LocalPresentationBoundary:
    def __init__(self, adapter: PresentationAdapter) -> None:
        self.adapter = adapter

    def open(
        self, command: SpeechPresentationCommand, policy: SpeechPresentationTimeoutPolicy
    ) -> LocalPresentationSession:
        return LocalPresentationSession(self.adapter(command))
