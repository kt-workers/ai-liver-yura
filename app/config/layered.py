"""少数の主設定からProfileを厳密に解決し、不変なOwner入力を供給する。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NoReturn

import yaml
from yaml.tokens import AliasToken

from app.config.s2_contracts import parse, shape
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.domain.speech_runtime.policy import (
    SpeechCandidatePriority,
    SpeechExpiryRule,
    SpeechPresentationTimeoutPolicy,
    SpeechQueueOverflowPolicy,
    SpeechRuntimeOperationalPolicy,
)

ROLES = (
    "speech_semantics",
    "character_language",
    "semantic_verification_blind_inventory",
    "semantic_verification_plan_relation",
)
MAX_FILE_BYTES = 262144


class ConfigurationFailureCode(str, Enum):
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    STALE = "STALE"
    BINDING_MISMATCH = "BINDING_MISMATCH"


class ConfigurationError(ValueError):
    """設定値、秘密、内部pathを含まない構成失敗。"""

    def __init__(self, code: ConfigurationFailureCode) -> None:
        self.code = code
        super().__init__(f"本番設定を使用できません: {code.value}")


def invalid() -> NoReturn:
    raise ConfigurationError(ConfigurationFailureCode.INVALID)


def _name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is None:
        invalid()
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        invalid()
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        invalid()
    return value


def _number(value: object) -> float:
    if type(value) not in (float, int):
        invalid()
    assert isinstance(value, (float, int))
    return float(value)


def _schema(data: dict[str, object], expected: str) -> None:
    if data["schema"] != expected:
        raise ConfigurationError(ConfigurationFailureCode.UNSUPPORTED)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def _revision(value: object) -> int:
    return int(_digest(value), 16) + 1


@dataclass(frozen=True, slots=True)
class SpeechProfile:
    identity: str
    revision: int
    executions: tuple[LLMExecutionPolicy, ...]
    runtime: SpeechRuntimeOperationalPolicy
    output_modes: tuple[SpeechPresentationMode, ...]
    tts_mode: TTSPreparationMode
    priority: SpeechCandidatePriority
    performance: str


@dataclass(frozen=True, slots=True)
class RoleDeployment:
    role_id: str
    model: str = field(repr=False)
    reasoning: str = field(repr=False)
    max_output_tokens: int | None
    temperature_range: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class SpeechDeploymentProfile:
    identity: str
    revision: int
    connection: str
    llm_availability: str
    roles: tuple[RoleDeployment, ...] = field(repr=False)
    tts_availability: str
    tts_provider: str | None = field(repr=False)
    tts_voice: str | None = field(repr=False)
    tts_locale: str | None = field(repr=False)
    presentation: str
    presentation_availability: str


@dataclass(frozen=True, slots=True)
class UserConfiguration:
    """解決済みの一組。内部revisionは入力項目ではない。"""

    revision: int
    speech: SpeechProfile | None
    deployment: SpeechDeploymentProfile | None


def _execution(value: object, policy_id: str) -> LLMExecutionPolicy:
    d = shape(
        value, "model_class reasoning timeout_seconds attempts output_tokens temperature retry"
    )
    retry = shape(d["retry"], "initial_seconds multiplier max_seconds")
    return LLMExecutionPolicy(
        policy_id,
        _revision(d),
        LLMModelClass(_text(d["model_class"])),
        LLMReasoningEffort(_text(d["reasoning"])),
        _number(d["timeout_seconds"]),
        _int(d["attempts"]),
        _int(d["output_tokens"]),
        LLMRequestRetryPolicy(
            _number(retry["initial_seconds"]),
            _number(retry["multiplier"]),
            _number(retry["max_seconds"]),
        ),
        None if d["temperature"] is None else _number(d["temperature"]),
    )


def _runtime(value: object, policy_id: str) -> SpeechRuntimeOperationalPolicy:
    d = shape(
        value,
        "queue_capacity in_flight background_in_flight regeneration_attempts "
        "expiry_seconds speculative_limit overflow presentation_timeout",
    )
    expiry = shape(d["expiry_seconds"], "background normal foreground direct_user")
    timeout = shape(
        d["presentation_timeout"],
        "start_report_timeout_seconds text_terminal_timeout_seconds audio_terminal_grace_seconds "
        "audio_terminal_fallback_timeout_seconds worker_grace_seconds "
        "worker_terminate_seconds worker_kill_seconds",
    )
    return SpeechRuntimeOperationalPolicy(
        policy_id,
        _revision(d),
        _int(d["queue_capacity"]),
        _int(d["in_flight"]),
        _int(d["background_in_flight"]),
        _int(d["regeneration_attempts"]),
        tuple(SpeechExpiryRule(p, _number(expiry[p.value])) for p in SpeechCandidatePriority),
        _int(d["speculative_limit"]),
        SpeechQueueOverflowPolicy(_text(d["overflow"])),
        SpeechPresentationTimeoutPolicy(**{k: _number(v) for k, v in timeout.items()}),
    )


def _speech(value: object, name: str) -> SpeechProfile:
    d = shape(value, "schema executions runtime output_modes tts_mode priority performance")
    _schema(d, "yura.speech-profile.v1")
    executions = shape(d["executions"], " ".join(ROLES))
    modes = d["output_modes"]
    if not isinstance(modes, list) or not modes or len(set(modes)) != len(modes):
        invalid()
    output = tuple(SpeechPresentationMode(_text(m)) for m in modes)
    if SpeechPresentationMode.FAIL_CLOSED in output:
        invalid()
    mode = TTSPreparationMode(_text(d["tts_mode"]))
    if mode is TTSPreparationMode.DISABLED or d["performance"] != "yura_revision_1":
        invalid()
    pid = "configuration.speech." + name
    return SpeechProfile(
        pid,
        _revision(d),
        tuple(_execution(executions[r], pid + "." + r) for r in ROLES),
        _runtime(d["runtime"], pid + ".runtime"),
        output,
        mode,
        SpeechCandidatePriority(_text(d["priority"])),
        _text(d["performance"]),
    )


def _availability(value: object) -> str:
    if value not in ("available", "unavailable"):
        invalid()
    return str(value)


def _deployment(value: object, name: str) -> SpeechDeploymentProfile:
    d = shape(value, "schema connection llm tts presentation")
    _schema(d, "yura.speech-deployment.v1")
    llm = shape(d["llm"], "availability roles")
    available = _availability(llm["availability"])
    roles: list[RoleDeployment] = []
    if available == "available":
        for role_id, raw in shape(llm["roles"], " ".join(ROLES)).items():
            row = shape(raw, "model reasoning max_output_tokens temperature_range")
            maximum = None if row["max_output_tokens"] is None else _int(row["max_output_tokens"])
            if maximum is not None and maximum < 1:
                invalid()
            temperature = row["temperature_range"]
            temperature_range = None
            if temperature is not None:
                bounds = shape(temperature, "minimum maximum")
                temperature_range = (_number(bounds["minimum"]), _number(bounds["maximum"]))
            roles.append(
                RoleDeployment(
                    role_id,
                    _text(row["model"]),
                    _text(row["reasoning"]),
                    maximum,
                    temperature_range,
                )
            )
    elif llm["roles"] is not None:
        invalid()
    tts = shape(d["tts"], "availability provider voice locale")
    tts_available = _availability(tts["availability"])
    values: tuple[str | None, str | None, str | None] = (None, None, None)
    if tts_available == "available":
        values = (_text(tts["provider"]), _text(tts["voice"]), _text(tts["locale"]))
    elif any(tts[k] is not None for k in ("provider", "voice", "locale")):
        invalid()
    presentation = shape(d["presentation"], "binding availability")
    return SpeechDeploymentProfile(
        "configuration.deployment." + name,
        _revision(d),
        _name(d["connection"]),
        available,
        tuple(roles),
        tts_available,
        *values,
        _name(presentation["binding"]),
        _availability(presentation["availability"]),
    )


def _read(root: Path, ref: str) -> object:
    path = root / ref
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            invalid()
        with resolved.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            invalid()
        for count, token in enumerate(yaml.scan(data)):
            if count > 20000 or isinstance(token, AliasToken):
                invalid()
        result = parse(data)
        _bounded(result, 0, [0])
        return result
    except FileNotFoundError:
        raise ConfigurationError(ConfigurationFailureCode.MISSING) from None


def _bounded(value: object, depth: int, count: list[int]) -> None:
    count[0] += 1
    if depth > 24 or count[0] > 10000:
        invalid()
    if isinstance(value, dict):
        for item in value.values():
            _bounded(item, depth + 1, count)
    elif isinstance(value, list):
        for item in value:
            _bounded(item, depth + 1, count)


def _load(root: Path) -> UserConfiguration:
    d = shape(_read(root, "user.yaml"), "schema speech")
    _schema(d, "yura.user.v1")
    if d["speech"] is None:
        return UserConfiguration(_revision(d), None, None)
    selection = shape(d["speech"], "profile deployment")
    name, deployment = _name(selection["profile"]), _name(selection["deployment"])
    speech_data = _read(root, f"profiles/speech/{name}.yaml")
    deployment_data = _read(root, f"profiles/deployment/{deployment}.yaml")
    speech = _speech(speech_data, name)
    resolved = _deployment(deployment_data, deployment)
    if (
        SpeechPresentationMode.AUDIO_WITH_TEXT in speech.output_modes
        and resolved.tts_availability != "available"
    ):
        invalid()
    return UserConfiguration(_revision([d, speech_data, deployment_data]), speech, resolved)


def load_user_configuration(root: Path) -> UserConfiguration:
    """明示root以外へ探索せず、読み取り中の構成変更も拒否する。"""
    try:
        result = _load(root)
        if result != _load(root):
            raise ConfigurationError(ConfigurationFailureCode.STALE)
        return result
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError(ConfigurationFailureCode.INVALID) from None
