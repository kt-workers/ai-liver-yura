"""音声の公開型を利用する本体が具体的なTTS実装を読み込まないことを検証する。"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module", ["app.domain.body_realtime", "app.domain.contracts.speech_audio"]
)
def test_public_audio_and_body_import_without_loading_tts_adapter(module):
    script = """
import importlib
import importlib.abc
import sys

class ForbiddenTTS(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.adapters.tts" or fullname.startswith("app.adapters.tts."):
            raise AssertionError("本体の読込みがTTSアダプターへ依存しています")
        return None

sys.meta_path.insert(0, ForbiddenTTS())
importlib.import_module(sys.argv[1])
assert not any(
    name == "app.adapters.tts" or name.startswith("app.adapters.tts.")
    for name in sys.modules
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, module], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr


def test_existing_adapter_exports_are_the_exact_public_types():
    from app.adapters.tts import contracts as adapter
    from app.domain.contracts import speech_audio as public

    for name in (
        "PreparedAudioArtifact",
        "SpeechTimingKind",
        "SpeechTimingSourceKind",
        "SpeechTimingQuality",
        "SpeechTimingUnit",
        "SpeechTimingTrack",
    ):
        assert getattr(adapter, name) is getattr(public, name)


def test_core_has_no_static_adapter_import_even_in_type_annotations():
    root = Path(__file__).resolve().parents[3] / "app"
    violations = []
    for directory in ("domain", "usecases", "runtime"):
        for path in (root / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                if any(
                    name == "app.adapters" or name.startswith("app.adapters.") for name in names
                ):
                    violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not violations, f"本体から具体アダプターへの参照: {violations}"
