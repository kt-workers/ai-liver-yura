"""旧構成モジュールの互換入口。実行判断の実装はUse Casesが所有する。"""

from app.usecases.brain_executive import ExecutiveBrainModulePort as ExecutiveBrainModulePort
from app.usecases.brain_executive import ExecutiveBrainWorkPayload as ExecutiveBrainWorkPayload
from app.usecases.executive_binding import CoreExecutiveBinding as CoreExecutiveBinding
from app.usecases.executive_evidence import (
    CoreExecutiveEvidence as CoreExecutiveEvidence,
    CoreExecutiveEvidenceReader as CoreExecutiveEvidenceReader,
)
