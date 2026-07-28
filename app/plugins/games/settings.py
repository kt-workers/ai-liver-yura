from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.config.errors import ConfigError
from app.config.strict import (
    optional_bool,
    optional_int,
    optional_mapping,
    optional_number,
    optional_string,
    reject_unknown_keys,
)


@dataclass(frozen=True, slots=True)
class GameIntentInterpreterSettings:
    enabled: bool = True
    model: str | None = None
    confidence_threshold: float = 0.85
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class ShiritoriPluginSettings:
    enabled: bool = True
    max_generation_retries: int = 3


@dataclass(frozen=True, slots=True)
class GamesPluginSettings:
    enabled: bool = True
    intent_interpreter: GameIntentInterpreterSettings = field(
        default_factory=GameIntentInterpreterSettings
    )
    shiritori: ShiritoriPluginSettings = field(default_factory=ShiritoriPluginSettings)

    def referenced_models(self) -> tuple[str, ...]:
        model = self.intent_interpreter.model
        if not self.enabled or not self.intent_interpreter.enabled or model is None:
            return ()
        return (model,)


def load_games_plugin_settings(
    value: object,
    *,
    path: str = "plugins.games",
) -> GamesPluginSettings:
    if value is None:
        return GamesPluginSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(path=path, expected="object", actual=type(value).__name__)
    config: dict[str, Any] = dict(value)
    reject_unknown_keys(config, {"enabled", "intent_interpreter", "shiritori"}, path)
    interpreter = optional_mapping(config, "intent_interpreter", path)
    shiritori = optional_mapping(config, "shiritori", path)
    reject_unknown_keys(
        interpreter,
        {"enabled", "model", "confidence_threshold", "max_attempts"},
        f"{path}.intent_interpreter",
    )
    reject_unknown_keys(
        shiritori,
        {"enabled", "max_generation_retries"},
        f"{path}.shiritori",
    )

    threshold = optional_number(
        interpreter,
        "confidence_threshold",
        f"{path}.intent_interpreter",
        default=0.85,
    )
    assert threshold is not None
    if not 0.0 <= threshold <= 1.0:
        raise ConfigError(
            path=f"{path}.intent_interpreter.confidence_threshold",
            expected="number between 0.0 and 1.0",
            actual="out of range",
        )
    max_attempts = optional_int(
        interpreter,
        "max_attempts",
        f"{path}.intent_interpreter",
        default=2,
    )
    assert max_attempts is not None
    if max_attempts <= 0:
        raise ConfigError(
            path=f"{path}.intent_interpreter.max_attempts",
            expected="integer greater than 0",
            actual="out of range",
        )
    max_retries = optional_int(
        shiritori,
        "max_generation_retries",
        f"{path}.shiritori",
        default=3,
    )
    assert max_retries is not None
    if max_retries < 0:
        raise ConfigError(
            path=f"{path}.shiritori.max_generation_retries",
            expected="integer greater than or equal to 0",
            actual="out of range",
        )
    return GamesPluginSettings(
        enabled=optional_bool(config, "enabled", path, default=True),
        intent_interpreter=GameIntentInterpreterSettings(
            enabled=optional_bool(
                interpreter,
                "enabled",
                f"{path}.intent_interpreter",
                default=True,
            ),
            model=optional_string(interpreter, "model", f"{path}.intent_interpreter"),
            confidence_threshold=threshold,
            max_attempts=max_attempts,
        ),
        shiritori=ShiritoriPluginSettings(
            enabled=optional_bool(shiritori, "enabled", f"{path}.shiritori", default=True),
            max_generation_retries=max_retries,
        ),
    )
