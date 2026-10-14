from __future__ import annotations

import pytest
import yaml

from app.config.core_contracts import CoreConfigurationError
from app.config.llm_connections import load_llm_connections

SOURCE = """\
schema_id: yura.llm-connections.v1
config_id: yura.llm-connections
config_revision: 1
llm_connections:
  - id: yura.llm.primary
    adapter: unavailable
    settings:
      availability: unavailable
"""


def test_loads_immutable_connection_settings() -> None:
    loaded = load_llm_connections(SOURCE)

    assert loaded.connections[0].connection_id == "yura.llm.primary"
    assert loaded.connections[0].settings == {"availability": "unavailable"}
    with pytest.raises(TypeError):
        loaded.connections[0].settings["availability"] = "configured"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: source | {"unexpected": None},
        lambda source: source | {"schema_id": "unknown"},
        lambda source: source | {"llm_connections": []},
        lambda source: source
        | {
            "llm_connections": source["llm_connections"]
            + [dict(source["llm_connections"][0])]
        },
    ],
)
def test_rejects_invalid_connection_collection(mutate: object) -> None:
    source = yaml.safe_load(SOURCE)
    with pytest.raises(CoreConfigurationError):
        load_llm_connections(yaml.safe_dump(mutate(source)))  # type: ignore[operator]
