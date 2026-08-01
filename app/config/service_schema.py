from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class OpenAiServiceSettings:
    base_url: str
    api_key_env: str
    timeout_seconds: float
    type: Literal["openai"] = field(default="openai", init=False)


@dataclass(frozen=True, slots=True)
class OllamaServiceSettings:
    base_url: str
    timeout_seconds: float
    type: Literal["ollama"] = field(default="ollama", init=False)


@dataclass(frozen=True, slots=True)
class VoiceVoxServiceSettings:
    base_url: str
    timeout_seconds: float
    type: Literal["voicevox"] = field(default="voicevox", init=False)


@dataclass(frozen=True, slots=True)
class PostgresServiceSettings:
    dsn_env: str
    type: Literal["postgres"] = field(default="postgres", init=False)


@dataclass(frozen=True, slots=True)
class DisabledServiceSettings:
    type: Literal["disabled"] = field(default="disabled", init=False)


ServiceSettings: TypeAlias = (
    OpenAiServiceSettings
    | OllamaServiceSettings
    | VoiceVoxServiceSettings
    | PostgresServiceSettings
    | DisabledServiceSettings
)

HttpAiServiceSettings: TypeAlias = (
    OpenAiServiceSettings | OllamaServiceSettings | VoiceVoxServiceSettings
)
