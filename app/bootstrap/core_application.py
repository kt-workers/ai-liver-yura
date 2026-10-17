"""起動済みCoreの所有とライフサイクルへの委譲。"""

from __future__ import annotations

import asyncio

from app.bootstrap.cognition_configuration import CoreCognitionConfiguration
from app.bootstrap.composition_contracts import SystemCompositionSnapshot
from app.bootstrap.core_components import CoreComponents
from app.config.appraisal_assembly import AppraisalProductionBinding
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.config.executive_assembly import ExecutiveProductionBinding
from app.usecases.core_lifecycle import CoreActivationError, CoreApplicationLifecycle
from app.usecases.resource_cleanup import OwnedResourceLedger


class CoreApplication:
    """構成情報を公開し、開始・終了を本体の実行所有者へ委譲する。"""

    __slots__ = (
        "core", "composition_snapshot", "cognition", "appraisal", "executive",
        "_owned", "_runtime",
    )

    def __init__(
        self,
        core: CoreComponents,
        composition_snapshot: SystemCompositionSnapshot,
        cognition: CoreCognitionConfiguration,
        appraisal: AppraisalProductionBinding,
        executive: ExecutiveProductionBinding,
        owned: OwnedResourceLedger,
    ) -> None:
        self.core = core
        self.composition_snapshot = composition_snapshot
        self.cognition = cognition
        self.appraisal = appraisal
        self.executive = executive
        self._owned = owned
        self._runtime = CoreApplicationLifecycle(core, owned)

    async def start(self) -> None:
        try:
            await self._runtime.start()
        except CoreActivationError:
            raise CoreConfigurationError(CoreFailureCode.ACTIVATION_FAILED) from None

    async def stop(self) -> None:
        try:
            await self._runtime.stop()
        except asyncio.CancelledError:
            raise
        except CoreConfigurationError:
            raise
        except Exception:
            # 内部の回収例外を公開契約へ正規化し、詳細例外を外へ漏らさない。
            raise CoreConfigurationError(CoreFailureCode.INITIALIZATION_FAILED) from None
