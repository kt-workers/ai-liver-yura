"""移行中の旧import入口。実行責務と型の定義はユースケース側が所有する。"""

from app.usecases.attention_binding import CoreAttentionBinding as CoreAttentionBinding
from app.usecases.attention_binding import CoreAttentionCurrentState as CoreAttentionCurrentState
from app.usecases.attention_binding import CoreAttentionDispatch as CoreAttentionDispatch
