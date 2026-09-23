"""注入された稼働設定から、公開を許可した項目だけを投影する。"""

from __future__ import annotations

import json
from datetime import timezone

from app.config.minimum_brain import MinimumBrainProductionConfig
from app.domain.contracts.common import thaw_json
from app.runtime.kernel.clock import RuntimeClock

from .contracts import (
    AdminReadModelEnvelope,
    GuiAdminConfigurationReadModel,
    GuiAdminOperationalPolicy,
    GuiAdminReadModelKind,
)


class MinimumBrainConfigurationReadModelProjector:
    """同じ不変設定の表示と生成時刻を構築時に固定する。"""

    def __init__(
        self,
        config: MinimumBrainProductionConfig,
        clock: RuntimeClock,
        policy: GuiAdminOperationalPolicy,
    ) -> None:
        if not isinstance(config, MinimumBrainProductionConfig):
            raise ValueError("注入された最小Brainの本番設定が必要です")
        if not isinstance(policy, GuiAdminOperationalPolicy):
            raise ValueError("GUIの運用方針が必要です")
        self.model = GuiAdminConfigurationReadModel(
            config_owner="yura.minimum-brain.production",
            schema_version=1,
            config_revision=config.config_revision,
            editable_fields=(),
            effective_values={
                "schema_id": config.schema_id,
                "config_id": config.config_id,
                "config_revision": config.config_revision,
                "brain_module_registrations": tuple(
                    module.value for module in config.brain_module_registrations
                ),
            },
            provenance={
                "config_id": config.config_id,
                "config_revision": config.config_revision,
            },
        )
        self.envelope = AdminReadModelEnvelope(
            model_kind=GuiAdminReadModelKind.CONFIGURATION_SUMMARY,
            schema_version=1,
            source_owner=self.model.config_owner,
            source_revision=self.model.config_revision,
            generated_at=clock.now(),
            payload={
                "config_owner": self.model.config_owner,
                "schema_version": self.model.schema_version,
                "config_revision": self.model.config_revision,
                "editable_fields": (),
                "secret_fields": (),
                "effective_values": self.model.effective_values,
                "provenance": self.model.provenance,
            },
        )
        self.json_bytes = json.dumps(
            {
                "model_kind": self.envelope.model_kind.value,
                "schema_version": self.envelope.schema_version,
                "source_owner": self.envelope.source_owner,
                "source_revision": self.envelope.source_revision,
                "generated_at": self.envelope.generated_at.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "availability": self.envelope.availability.value,
                "degraded_reasons": list(self.envelope.degraded_reasons),
                "payload": thaw_json(self.envelope.payload),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(self.json_bytes) > policy.max_read_model_payload_bytes:
            raise ValueError("GUI表示モデルの全体が容量上限を超えています")
