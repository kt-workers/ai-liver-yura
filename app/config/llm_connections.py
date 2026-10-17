"""LLM接続の設定集合を、認知用途から独立して読み込む。"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.core_contracts import identity, invalid, parse, revision, shape
from app.domain.contracts.common import freeze_json


@dataclass(frozen=True, slots=True)
class LLMConnectionConfig:
    """一つのLLM接続。接続先の差異はadapterだけが解釈する。"""

    connection_id: str
    adapter_id: str
    settings: object

    def __post_init__(self) -> None:
        identity(self.connection_id)
        identity(self.adapter_id)
        object.__setattr__(self, "settings", freeze_json(self.settings))


@dataclass(frozen=True, slots=True)
class LLMConnectionsConfig:
    schema_id: str
    config_id: str
    config_revision: int
    connections: tuple[LLMConnectionConfig, ...]

    def __post_init__(self) -> None:
        if self.schema_id != "yura.llm-connections.v1":
            invalid()
        identity(self.config_id)
        revision(self.config_revision)
        values = tuple(self.connections)
        if not values or any(not isinstance(value, LLMConnectionConfig) for value in values):
            invalid()
        if len({value.connection_id for value in values}) != len(values):
            invalid()
        object.__setattr__(self, "connections", values)


def load_llm_connections(source: str | bytes) -> LLMConnectionsConfig:
    data = shape(parse(source), "schema_id config_id config_revision llm_connections")
    values = data["llm_connections"]
    if not isinstance(values, list):
        invalid()
    connections: list[LLMConnectionConfig] = []
    for value in values:
        item = shape(value, "id adapter settings")
        connections.append(
            LLMConnectionConfig(
                identity(item["id"]), identity(item["adapter"]), item["settings"]
            )
        )
    return LLMConnectionsConfig(
        identity(data["schema_id"]),
        identity(data["config_id"]),
        revision(data["config_revision"]),
        tuple(connections),
    )
