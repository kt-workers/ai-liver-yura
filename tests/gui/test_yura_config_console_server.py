from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "gui" / "yura-config-console" / "server.py"
SPEC = importlib.util.spec_from_file_location("yura_config_console_server", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def test_boolean_metadata_uses_schema_instead_of_saved_value() -> None:
    fields = server.metadata_for("character", {"casual_speech": 1})

    assert fields[0]["type"] == "boolean"


def test_boolean_legacy_values_are_normalized_before_validation() -> None:
    for raw, expected in [(0, False), (1, True), ("off", False), ("on", True)]:
        values = server.normalize_values("runtime", {
            **server.DEFAULT_VALUES["runtime"],
            "timer_enabled": raw,
        })

        assert values["timer_enabled"] is expected
        assert server.validate_values("runtime", values) == []


def test_boolean_fields_do_not_report_integer_error() -> None:
    values = {
        **server.DEFAULT_VALUES["character"],
        "casual_speech": "invalid",
    }

    errors = server.validate_values("character", values)

    assert errors == [{"field": "casual_speech", "message": "オンまたはオフを指定してください。"}]
