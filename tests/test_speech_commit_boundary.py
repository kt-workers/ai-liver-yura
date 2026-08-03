from __future__ import annotations

import pytest

from app.domain.actions import ActionPlan, ActionPlanGroup, ActionType
from app.domain.activity_turn_result import ActivityOutputStatus
from app.domain.character_response import VoiceIntent
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.autonomous_output import completed_speech_text
from app.usecases import ExecuteActionUsecase


class FailingSpeechSynthesizer:
    async def synthesize(
        self,
        text: str,
        voice_intent: VoiceIntent | None = None,
    ) -> bytes:
        raise RuntimeError("VOICEVOX unavailable")


class FakeAudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        raise AssertionError("音声合成失敗時に再生してはいけない")


class FakeTopicClassifier:
    def __init__(self) -> None:
        self.classified_texts: list[str] = []

    async def classify(self, text: str) -> TopicCategory:
        self.classified_texts.append(text)
        return TopicCategory.OTHER


class FakeEmbeddingGenerator:
    def __init__(self) -> None:
        self.received_texts: list[str] = []

    async def generate_embedding(self, text: str) -> list[float]:
        self.received_texts.append(text)
        return [0.1, 0.2]


class FakeTopicMemoryStore:
    def __init__(self) -> None:
        self.saved_entries: list[TopicMemoryEntry] = []

    async def save(self, entry: TopicMemoryEntry) -> None:
        self.saved_entries.append(entry)

    async def fetch_recent(self, limit: int = 10) -> list[TopicMemoryEntry]:
        return []

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 5,
    ) -> list[SimilarTopicMemory]:
        return []


@pytest.mark.asyncio
async def test_text_commit_completes_speak_without_voicevox(monkeypatch) -> None:
    async def no_wait(duration: float) -> None:
        return None

    monkeypatch.setattr(
        "app.usecases.execute_action_usecase.asyncio.sleep",
        no_wait,
    )
    topic_history = TopicHistory()
    classifier = FakeTopicClassifier()
    embedding = FakeEmbeddingGenerator()
    store = FakeTopicMemoryStore()
    executor = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=classifier,
        embedding_generator=embedding,
        topic_memory_store=store,
        speech_synthesizer=FailingSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
    )
    scheduler = ActionScheduler(executor)
    action = ActionPlan(
        action_type=ActionType.SPEAK,
        text="音声がなくても、この発話は完了する。",
        source_activity_id="autonomous-1",
    )
    group = ActionPlanGroup(
        action_plans=[action],
        source_activity_id="autonomous-1",
    )

    output = await scheduler.execute(group)

    assert output.status == ActivityOutputStatus.COMPLETED
    assert completed_speech_text(group, output) == action.text
    assert classifier.classified_texts == [action.text]
    assert embedding.received_texts == [action.text]
    assert len(store.saved_entries) == 1
    assert store.saved_entries[0].source_text == action.text
