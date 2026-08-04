# Body Runtime結合確認

この検証Runtimeは、Coreの`feature/avatar-performance-plan`から送られる
重複Track型`AvatarPerformancePlan`を棒人間へ反映する。

## 棒人間側

```bash
python gui/yura-avatar-runtime-lab/server.py
```

ブラウザ：`http://127.0.0.1:8000`

## Core側

別worktreeまたは別cloneでCoreブランチを起動する。

```bash
YURA_WEB_CONVERSATION_ENABLED=0 \
YURA_AVATAR_OUTPUT_ENABLED=1 \
YURA_AVATAR_RUNTIME_URL=http://127.0.0.1:8000 \
YURA_BODY_RUNTIME_ENABLED=1 \
YURA_BODY_TICK_HZ=30 \
python -m app
```

起動直後から`breathing`と`micro_sway`を確認できる。会話時には、表情、注意、首、
胴体、左右腕のTrackが重なって送信される。

棒人間側は、Core Body Runtimeが生成する次の追加プリミティブを描画する。

- `breathing`
- `micro_sway`
- `recoil`
- `open_outward`
- `straighten`
- `posture_open`
- `posture_closed`
- `posture_forward`
- `posture_withdrawn`

本ファイルを含む`test/*`ブランチは検証専用であり、developへマージしない。
