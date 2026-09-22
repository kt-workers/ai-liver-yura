"""GUIが所有する配置設定と通信上限を、不正値の補完なしで読み込む。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import yaml
from yaml.nodes import MappingNode

from app.subsystems.gui_admin.contracts import GuiAdminAccessLevel, GuiAdminOperationalPolicy


@dataclass(frozen=True, slots=True)
class GuiAdminHttpTransportPolicy:
    policy_id: str
    policy_revision: int
    max_concurrent_requests: int
    request_timeout_seconds: float
    shutdown_grace_seconds: float
    max_request_line_bytes: int
    max_header_field_bytes: int
    max_header_count: int
    max_request_body_bytes: int

    def __post_init__(self) -> None:
        if self.policy_id != "v2.gui-admin-http.local-readonly":
            raise ValueError("GUI通信方針の識別子が不正です")
        for name in (
            "policy_revision",
            "max_concurrent_requests",
            "max_request_line_bytes",
            "max_header_field_bytes",
            "max_header_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError("GUI通信上限には正の整数が必要です")
        if self.policy_revision != 1:
            raise ValueError("GUI通信方針のリビジョンが未対応です")
        if type(self.max_request_body_bytes) is not int or self.max_request_body_bytes != 0:
            raise ValueError("GUI要求本文は受け付けられません")
        for value in (self.request_timeout_seconds, self.shutdown_grace_seconds):
            if type(value) not in (float, int) or not isfinite(value) or value <= 0:
                raise ValueError("GUI通信時間には正の有限数が必要です")


@dataclass(frozen=True, slots=True)
class GuiAdminProductionConfig:
    schema_id: str
    config_id: str
    config_revision: int
    deployment_mode: str
    bind_host: str
    port: int
    access_level: GuiAdminAccessLevel
    gui_operational_policy: GuiAdminOperationalPolicy
    gui_http_transport_policy: GuiAdminHttpTransportPolicy

    def __post_init__(self) -> None:
        if (
            self.schema_id != "yura.gui-admin.production-config.v1"
            or self.config_id != "yura.gui-admin.production"
            or type(self.config_revision) is not int
            or self.config_revision < 1
        ):
            raise ValueError("GUI設定の識別子またはリビジョンが不正です")
        if (
            self.deployment_mode != "local_read_only"
            or self.bind_host != "127.0.0.1"
            or self.access_level is not GuiAdminAccessLevel.PUBLIC_VISUALIZATION
        ):
            raise ValueError("GUIの待受またはアクセス設定が不正です")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("GUIのポートが不正です")
        if not isinstance(self.gui_operational_policy, GuiAdminOperationalPolicy):
            raise ValueError("GUI運用方針が必要です")
        if not isinstance(self.gui_http_transport_policy, GuiAdminHttpTransportPolicy):
            raise ValueError("GUI通信方針が必要です")


class _Loader(yaml.SafeLoader):
    """重複キーを黙って上書きしない。"""


def _unique(loader: _Loader, node: MappingNode, deep: bool = False) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("GUI設定のキーが不正です")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique)


def _mapping(value: object, fields: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("GUI設定の項目が一致しません")
    return {str(key): item for key, item in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("GUI設定の文字列が不正です")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("GUI設定の整数が不正です")
    assert isinstance(value, int)
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("GUI設定の数値が不正です")
    assert isinstance(value, (int, float))
    return float(value)


def load_gui_admin_config(source: str | bytes) -> GuiAdminProductionConfig:
    """入力や解析例外を露出せず、純粋な構成値として読み込む。"""
    try:
        data = _mapping(
            yaml.load(source, Loader=_Loader),
            "schema_id config_id config_revision deployment_mode bind_host port access_level "
            "gui_operational_policy gui_http_transport_policy",
        )
        operational = _mapping(
            data["gui_operational_policy"],
            "policy_id policy_revision max_read_model_payload_bytes max_command_payload_bytes "
            "per_client_update_capacity max_history_page_items max_active_subscriptions_per_client "
            "max_in_flight_commands command_timeout_seconds",
        )
        transport = _mapping(
            data["gui_http_transport_policy"],
            "policy_id policy_revision max_concurrent_requests request_timeout_seconds "
            "shutdown_grace_seconds max_request_line_bytes max_header_field_bytes "
            "max_header_count max_request_body_bytes",
        )
        return GuiAdminProductionConfig(
            _text(data["schema_id"]),
            _text(data["config_id"]),
            _integer(data["config_revision"]),
            _text(data["deployment_mode"]),
            _text(data["bind_host"]),
            _integer(data["port"]),
            GuiAdminAccessLevel(_text(data["access_level"])),
            GuiAdminOperationalPolicy(
                _text(operational["policy_id"]),
                _integer(operational["policy_revision"]),
                _integer(operational["max_read_model_payload_bytes"]),
                _integer(operational["max_command_payload_bytes"]),
                _integer(operational["per_client_update_capacity"]),
                _integer(operational["max_history_page_items"]),
                _integer(operational["max_active_subscriptions_per_client"]),
                _integer(operational["max_in_flight_commands"]),
                _number(operational["command_timeout_seconds"]),
            ),
            GuiAdminHttpTransportPolicy(
                _text(transport["policy_id"]),
                _integer(transport["policy_revision"]),
                _integer(transport["max_concurrent_requests"]),
                _number(transport["request_timeout_seconds"]),
                _number(transport["shutdown_grace_seconds"]),
                _integer(transport["max_request_line_bytes"]),
                _integer(transport["max_header_field_bytes"]),
                _integer(transport["max_header_count"]),
                _integer(transport["max_request_body_bytes"]),
            ),
        )
    except (yaml.YAMLError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("GUIの本番設定を読み込めません") from None
