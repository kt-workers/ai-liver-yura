"""移行中の旧公開入口。実行責務は本体の実行カーネルが所有する。"""

from app.runtime.kernel.queue import BoundedWorkQueue as BoundedWorkQueue
from app.runtime.kernel.queue import Coalescer as Coalescer
