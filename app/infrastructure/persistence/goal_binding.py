"""移行中の旧公開入口。目標の確定・復元・保存確認はApplicationが所有する。"""

from app.usecases.goal_persistence import CoreGoalPersistenceBinding as CoreGoalPersistenceBinding
from app.usecases.goal_persistence import GoalPersistenceCommitResult as GoalPersistenceCommitResult
