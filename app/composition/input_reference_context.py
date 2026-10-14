"""移行中の旧import入口。実行責務と型の定義はユースケース側が所有する。"""

from app.usecases.input_reference_context import CoreGoalSnapshotReader as CoreGoalSnapshotReader
from app.usecases.input_reference_context import (
    CoreInputReferenceContextBinding as CoreInputReferenceContextBinding,
)
from app.usecases.input_reference_context import (
    CoreInputReferenceSnapshot as CoreInputReferenceSnapshot,
)
from app.usecases.input_reference_context import (
    PresentationReferenceCapacityError as PresentationReferenceCapacityError,
)
from app.usecases.input_reference_context import (
    PresentationReferenceStaleError as PresentationReferenceStaleError,
)
