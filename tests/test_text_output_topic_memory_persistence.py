from __future__ import annotations

import pytest

from app.domain.actions import ActionPlan, ActionType
from app.domain.character_response import VoiceIntent
from app.domain.topic import TopicCategory, TopicHistory
from app.domain.topic_memory import SimilarTopicMemory, TopicMemoryEntry
from app.usecases import ExecuteActionUsecase


class FailingSpeechSynthesizer:
    async def synthesize(
        self, text: str, voice_intent: VoiceIntent | None = None
    ) -> bytes:
        raise RuntimeError("VOICEVOX unavailable")


class FakeAudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        return None


class FakeConversationOutputPublisher:
    def __init__(self) -> None:
        self.outputs: list[tuple[str, str, str]] = []

    async def publish_text(self, *, kind: str, text: str, action_id: str) -> None:
        self.outputs.append((kind, text, action_id))


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
        return [0.1, 0.2, 0.3]


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
async def test_voice_failure_persists_topic_memory_after_text_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def no_wait(duration: float) -> None:
        return None

    monkeypatch.setattr(
        "app.usecases.execute_action_usecase.asyncio.sleep",
        no_wait,
    )
    topic_history = TopicHistory()
    classifier = FakeTopicClassifier()
    embedding_generator = FakeEmbeddingGenerator()
    store = FakeTopicMemoryStore()
    output = FakeConversationOutputPublisher()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=store,
        speech_synthesizer=FailingSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
        conversation_output_publisher=output,
    )
    action = ActionPlan(
        action_type=ActionType.SPEAK,
        text="音声がなくても、この発話は表示されたよ。",
        source_activity_id="activity-1",
        output_unit_id="output-1",
    )

    result = await usecase.execute(action)

    assert output.outputs == [("speak", action.text, action.action_id)]
    assert f"[speak] {action.text}" in capsys.readouterr().out
    assert classifier.classified_texts == [action.text]
    assert embedding_generator.received_texts == [action.text]
    assert len(topic_history.recent_entries()) == 1
    assert len(store.saved_entries) == 1
    assert store.saved_entries[0].source_text == action.text
    assert store.saved_entries[0].source_activity_id == "activity-1"
    assert result is not None
    assert result.status.value == "failed"
    assert "VOICEVOX unavailable" in (result.error or "")


@pytest.mark.asyncio
async def test_voice_failure_respects_skip_topic_memory_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(duration: float) -> None:
        return None

    monkeypatch.setattr(
        "app.usecases.execute_action_usecase.asyncio.sleep",
        no_wait,
    )
    topic_history = TopicHistory()
    classifier = FakeTopicClassifier()
    embedding_generator = FakeEmbeddingGenerator()
    store = FakeTopicMemoryStore()
    usecase = ExecuteActionUsecase(
        topic_history=topic_history,
        topic_classifier=classifier,
        embedding_generator=embedding_generator,
        topic_memory_store=store,
        speech_synthesizer=FailingSpeechSynthesizer(),
        audio_player=FakeAudioPlayer(),
    )

    result = await usecase.execute(
        ActionPlan(
            action_type=ActionType.SPEAK,
            text="保存対象外の一時的な発話",
            metadata={"skip_topic_memory": True},
        )
    )

    assert classifier.classified_texts == []
    assert embedding_generator.received_texts == []
    assert topic_history.recent_entries() == []
    assert store.saved_entries == []
    assert result is not None
    assert result.status.value == "failed"
