"""External-I/O-free output adapters for Core runtime tests."""

from __future__ import annotations

from app.domain.character_response import VoiceIntent


class FakeSpeechSynthesizer:
    async def synthesize(self, text: str, voice_intent: VoiceIntent | None = None) -> bytes:
        del voice_intent
        return f"DEMO_AUDIO:{text}".encode()


class FakeAudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        del audio_data
