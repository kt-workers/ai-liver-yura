from __future__ import annotations

import logging
from typing import Any, cast

from app.domain.avatar_performance import AvatarPerformancePlan
from app.ports.avatar_output import AvatarGazeIntent, AvatarOutputPort
from app.shared.contracts.plugins.runtime import CapabilityReporter, PluginContext


class AvatarOutputPlugin:
    """Live2D/3D Adapterを任意Capabilityとして隔離するPlugin。"""

    plugin_id = "avatar_output"
    display_name = "Avatar Output"
    PERFORMANCE_CAPABILITY = "output.avatar.performance"
    EXPRESSION_CAPABILITY = "output.avatar.expression"
    GESTURE_CAPABILITY = "output.avatar.gesture"
    GAZE_CAPABILITY = "output.avatar.gaze"

    def __init__(self, adapter: AvatarOutputPort | Any | None) -> None:
        self._adapter = adapter
        self._initialized = False
        self._healthy = False
        self._unavailable_capabilities: set[str] = set()
        self._capability_reporter: CapabilityReporter | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(
            {
                self.PERFORMANCE_CAPABILITY,
                self.EXPRESSION_CAPABILITY,
                self.GESTURE_CAPABILITY,
                self.GAZE_CAPABILITY,
            }
        )

    def available_capabilities(self) -> frozenset[str]:
        if not self._initialized or not self._healthy:
            return frozenset()
        return self.capabilities.difference(self._unavailable_capabilities)

    def initialize(self, context: PluginContext) -> None:
        self._capability_reporter = context.capability_reporter
        self._initialized = True
        self._healthy = self._adapter is not None
        self._unavailable_capabilities.clear()
        if self._adapter is not None and not callable(
            getattr(self._adapter, "submit_performance", None)
        ):
            # 既存Adapterは個別Actionで利用し、Performanceだけを非対応とする。
            self._unavailable_capabilities.add(self.PERFORMANCE_CAPABILITY)
        # 初期Capability登録はinitialize()後にPluginManagerが実施する。
        self._logger.info(
            "avatar output initialized: available=%s performance=%s",
            self._healthy,
            self.PERFORMANCE_CAPABILITY not in self._unavailable_capabilities,
        )

    def shutdown(self) -> None:
        self._initialized = False
        self._healthy = False
        self._unavailable_capabilities.clear()
        self._capability_reporter = None

    async def submit_performance(
        self,
        performance: AvatarPerformancePlan,
    ) -> None:
        adapter = self._require_adapter(self.PERFORMANCE_CAPABILITY)
        submit = getattr(adapter, "submit_performance", None)
        if not callable(submit):
            self._mark_capability_unavailable(
                self.PERFORMANCE_CAPABILITY,
                "performance_unsupported",
                RuntimeError("adapter does not support performance submission"),
            )
            raise RuntimeError(
                f"avatar_output.unavailable:{self.PERFORMANCE_CAPABILITY}"
            )
        try:
            await submit(performance)
        except Exception as error:
            # Performance APIだけが未実装・停止していても、個別Actionへ縮退できる。
            self._mark_capability_unavailable(
                self.PERFORMANCE_CAPABILITY,
                "performance_failed",
                error,
            )
            raise

    async def set_expression(self, expression: str) -> None:
        adapter = self._require_adapter(self.EXPRESSION_CAPABILITY)
        try:
            await adapter.set_expression(expression)
        except Exception as error:
            self._mark_all_unavailable("expression_failed", error)
            raise

    async def play_gesture(self, gesture: str) -> None:
        adapter = self._require_adapter(self.GESTURE_CAPABILITY)
        try:
            await adapter.play_gesture(gesture)
        except Exception as error:
            self._mark_all_unavailable("gesture_failed", error)
            raise

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        adapter = self._require_adapter(self.GAZE_CAPABILITY)
        try:
            await adapter.set_gaze(gaze)
        except Exception as error:
            self._mark_all_unavailable("gaze_failed", error)
            raise

    def _require_adapter(self, capability: str) -> AvatarOutputPort:
        if (
            not self._initialized
            or not self._healthy
            or self._adapter is None
            or capability in self._unavailable_capabilities
        ):
            raise RuntimeError(f"avatar_output.unavailable:{capability}")
        return cast(AvatarOutputPort, self._adapter)

    def _mark_capability_unavailable(
        self,
        capability: str,
        reason: str,
        error: Exception,
    ) -> None:
        self._unavailable_capabilities.add(capability)
        if self._capability_reporter is not None:
            self._capability_reporter.set_capability_availability(
                self.plugin_id,
                capability,
                available=False,
            )
        self._logger.warning(
            "avatar output capability lost: capability=%s reason=%s error=%s",
            capability,
            reason,
            type(error).__name__,
        )

    def _mark_all_unavailable(self, reason: str, error: Exception) -> None:
        self._healthy = False
        self._unavailable_capabilities.update(self.capabilities)
        self._report_all_unavailable()
        self._logger.warning(
            "avatar output capabilities lost: reason=%s error=%s",
            reason,
            type(error).__name__,
        )

    def _report_all_unavailable(self) -> None:
        if self._capability_reporter is None:
            return
        for capability in self.capabilities:
            self._capability_reporter.set_capability_availability(
                self.plugin_id,
                capability,
                available=False,
            )
