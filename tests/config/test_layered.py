"""設定の欠落・差替え・不変性を実Profileから検証する。"""

import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.layered import ROLES, ConfigurationError, load_user_configuration

PROFILE = Path("resources/config/v2/profiles/speech/conservative.yaml")


def configured_root(root: Path, *, available: bool = False) -> Path:
    """外部I/O選択だけを試験用に指定し、Owner policyは同梱Profileを読む。"""
    (root / "profiles/speech").mkdir(parents=True)
    (root / "profiles/deployment").mkdir(parents=True)
    shutil.copy(PROFILE, root / "profiles/speech/conservative.yaml")
    write(
        root / "user.yaml",
        {"schema": "yura.user.v1", "speech": {"profile": "conservative", "deployment": "isolated"}},
    )
    write(
        root / "profiles/deployment/isolated.yaml",
        {
            "schema": "yura.speech-deployment.v1",
            "connection": "isolated",
            "llm": {
                "availability": "available" if available else "unavailable",
                "roles": {
                    r: {
                        "model": "external-test-model",
                        "reasoning": "external-test-effort",
                        "max_output_tokens": 8192,
                        "temperature_range": None,
                    }
                    for r in ROLES
                }
                if available
                else None,
            },
            "tts": {"availability": "unavailable", "provider": None, "voice": None, "locale": None},
            "presentation": {"binding": "isolated-display", "availability": "available"},
        },
    )
    return root


def write(path: Path, value: Any) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def edit(path: Path, keys: tuple[str, ...], value: Any) -> None:
    data = yaml.safe_load(path.read_text())
    current = data
    for key in keys[:-1]:
        current = current[key]
    current[keys[-1]] = value
    write(path, data)


def test_default_disabled_and_explicit_profile_is_immutable(tmp_path: Path) -> None:
    default = load_user_configuration(Path("resources/config/v2"))
    assert default.speech is None and default.deployment is None
    root = configured_root(tmp_path)
    config = load_user_configuration(root)
    assert config.speech is not None
    assert config.speech.runtime.max_in_flight_preparations == 2
    assert all(p.policy_id.startswith("configuration.speech.") for p in config.speech.executions)
    assert config == load_user_configuration(root)
    with pytest.raises(FrozenInstanceError):
        config.revision = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "keys,value",
    [
        (("schema",), "future"),
        (("runtime", "queue_capacity"), True),
        (("runtime", "background_in_flight"), 3),
        (("runtime", "in_flight"), 0),
        (("runtime", "expiry_seconds", "normal"), -1),
        (("runtime", "generation"), 2),
        (("output_modes",), []),
        (("output_modes",), ["text_only", "text_only"]),
        (("output_modes",), ["fail_closed"]),
        (("tts_mode",), "disabled"),
        (("performance",), "invented"),
        (("executions", "speech_semantics", "timeout_seconds"), float("nan")),
        (("executions", "speech_semantics", "attempts"), 0),
        (("executions", "speech_semantics", "output_tokens"), False),
        (("executions", "speech_semantics", "retry", "multiplier"), 0.5),
        (("executions", "speech_semantics", "instructions"), "非公開の入力"),
    ],
)
def test_invalid_profile_is_not_repaired(tmp_path: Path, keys: tuple[str, ...], value: Any) -> None:
    root = configured_root(tmp_path)
    edit(root / "profiles/speech/conservative.yaml", keys, value)
    with pytest.raises(ConfigurationError) as error:
        load_user_configuration(root)
    assert "非公開" not in str(error.value) and str(root) not in str(error.value)


@pytest.mark.parametrize(
    "keys,value",
    [
        (("speech", "profile"), "../outside"),
        (("speech", "deployment"), "/private/secret"),
        (("speech", "profile"), "missing"),
        (("secret",), "非公開token"),
    ],
)
def test_bad_selection_and_secret_field_rejected(
    tmp_path: Path, keys: tuple[str, ...], value: Any
) -> None:
    root = configured_root(tmp_path)
    edit(root / "user.yaml", keys, value)
    with pytest.raises(ConfigurationError) as error:
        load_user_configuration(root)
    assert str(root) not in str(error.value) and "非公開token" not in str(error.value)


@pytest.mark.parametrize(
    "text",
    [
        "schema: yura.user.v1\nspeech: null\nspeech: null\n",
        "schema: yura.user.v1\nspeech: &x [*x]\n",
        "[",
        "x" * 262145,
    ],
)
def test_malformed_duplicate_cycle_and_oversize(tmp_path: Path, text: str) -> None:
    (tmp_path / "user.yaml").write_text(text)
    with pytest.raises(ConfigurationError):
        load_user_configuration(tmp_path)


def test_escape_symlink_rejected(tmp_path: Path) -> None:
    root = configured_root(tmp_path / "root")
    outside = tmp_path / "outside.yaml"
    outside.write_text("schema: yura.speech-profile.v1")
    path = root / "profiles/speech/conservative.yaml"
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ConfigurationError):
        load_user_configuration(root)


def test_revision_tracks_content_not_yaml_format(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    first = load_user_configuration(root)
    path = root / "profiles/speech/conservative.yaml"
    path.write_text(path.read_text() + "\n# 説明だけ\n")
    assert load_user_configuration(root) == first
    edit(path, ("runtime", "queue_capacity"), 5)
    second = load_user_configuration(root)
    assert first.revision != second.revision
    assert first.speech is not None and second.speech is not None
    assert first.speech.identity == second.speech.identity
    assert first.speech.revision != second.speech.revision
    assert first.speech.executions == second.speech.executions


def test_no_voice_fallback_and_changeable_external_mapping(tmp_path: Path) -> None:
    root = configured_root(tmp_path, available=True)
    original = load_user_configuration(root)
    path = root / "profiles/deployment/isolated.yaml"
    edit(path, ("llm", "roles", "speech_semantics", "model"), "different-external-model")
    changed = load_user_configuration(root)
    assert original.deployment != changed.deployment
    assert original.speech == changed.speech
    edit(path, ("tts", "availability"), "available")
    with pytest.raises(ConfigurationError):
        load_user_configuration(root)


def test_audio_requires_explicit_available_tts(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    edit(root / "profiles/speech/conservative.yaml", ("output_modes",), ["audio_with_text"])
    with pytest.raises(ConfigurationError):
        load_user_configuration(root)
