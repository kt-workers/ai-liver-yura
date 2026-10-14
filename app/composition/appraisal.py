"""移行中の旧import入口。実行責務と型の定義はユースケース側が所有する。"""

from app.usecases.brain_appraisal import AppraisalBrainModulePort as AppraisalBrainModulePort
from app.usecases.brain_appraisal import AppraisalBrainWorkPayload as AppraisalBrainWorkPayload
from app.usecases.brain_appraisal import CoreAppraisalBinding as CoreAppraisalBinding
