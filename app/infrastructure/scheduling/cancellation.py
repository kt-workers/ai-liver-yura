"""移行中の旧公開入口。実行責務は本体の実行カーネルが所有する。"""

from app.runtime.kernel.cancellation import CancellationRegistry as CancellationRegistry
from app.runtime.kernel.cancellation import CancellationToken as CancellationToken
