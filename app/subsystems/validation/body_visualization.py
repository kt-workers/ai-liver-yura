"""本番の姿勢と運動学計算だけから、単独で開ける三面図を作る。"""

from html import escape

from app.domain.body import CanonicalBodyModel, Vector3
from app.domain.body_solver import BodyPoseFrame
from app.domain.body_solver.kinematics import forward_kinematics
from app.domain.body_solver.physical import end_effector_world_frame

from .contracts import positive


def render_body_pose_sequence(
    model: CanonicalBodyModel,
    frames: tuple[BodyPoseFrame, ...],
    *,
    max_frames: int,
    max_bytes: int,
) -> str:
    """姿勢の補間や生成をせず、記録済みの姿勢を観測間隔で再生する。"""
    positive(max_frames)
    positive(max_bytes)
    if not frames or len(frames) > max_frames:
        raise ValueError("表示する姿勢の数が空か上限を超えています")
    worlds: list[dict[str, Vector3]] = []
    ends: list[dict[str, Vector3]] = []
    previous: BodyPoseFrame | None = None
    for frame in frames:
        if frame.body_model_id != model.body_model_id:
            raise ValueError("姿勢と身体モデルが一致しません")
        if previous is not None and (
            frame.body_state_revision <= previous.body_state_revision
            or frame.observed_at < previous.observed_at
        ):
            raise ValueError("姿勢の版と観測時刻は記録順で渡してください")
        worlds.append(
            {
                joint_id: transform.position
                for joint_id, transform in forward_kinematics(model, frame.pose)
            }
        )
        ends.append(
            {
                item.end_effector_id: end_effector_world_frame(
                    model, frame.pose, item.end_effector_id
                ).position
                for item in model.end_effectors
            }
        )
        previous = frame

    # 全時点で共通の縮尺を使い、移動を毎回の自動拡大で打ち消さない。
    axes = ("x", "y", "z")
    values = {
        axis: [float(getattr(p, axis)) for w in worlds + ends for p in w.values()] for axis in axes
    }
    centers = {axis: (min(values[axis]) + max(values[axis])) / 2 for axis in axes}
    span = max(max(values[axis]) - min(values[axis]) for axis in axes)
    scale = 230 / max(span, model.reference_height * 0.1)
    views = (("x", "y"), ("z", "y"), ("x", "z"))
    parts = [
        '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>身体の姿勢記録</title>
<style>
body{font-family:system-ui,sans-serif;background:#101a2a;color:#e8eff9;margin:24px}
main{max-width:1120px;margin:auto}button,input{font:inherit;margin:6px;padding:8px}
svg{width:100%;background:#17263d;border-radius:12px}text{fill:#e8eff9;font-size:12px}
line.effector{stroke:#eeaeff;stroke-width:3}line.bone{stroke:#64dfc5;stroke-width:3}circle{fill:#ffc66d}
line.axis{stroke:#61738f;stroke-width:1}pre{white-space:pre-wrap}button{cursor:pointer}
[hidden]{display:none!important}.muted{color:#aabbd0}
</style><main><h1>身体の姿勢記録</h1>
<p>本番の姿勢を三方向から表示します。表示は平行投影です。</p>
<p>緑は関節の接続、紫は関節から末端への接続です。姿勢の補間や動作の生成は行いません。</p>
<div><button id="play" type="button">再生</button>
<label>姿勢 <input id="seek" type="range" min="0" value="0" step="1"'''
    ]
    parts.append(
        f' max="{len(frames) - 1}"></label><output id="position">1 / {len(frames)}</output></div>'
    )
    parts.append(f"<p>身体モデル: {escape(model.body_model_id)}</p>")
    total = sum(len(item.encode("utf-8")) for item in parts)
    for index, (frame, world, end) in enumerate(zip(frames, worlds, ends, strict=True)):
        offset = (frame.observed_at - frames[0].observed_at).total_seconds() * 1000
        block = [f'<section class="pose" data-offset="{offset:.6f}"{" hidden" if index else ""}>']
        block.append(
            f"<p>姿勢 {escape(frame.frame_id)} / 状態版 {frame.body_state_revision} / "
            f"観測 {escape(frame.observed_at.isoformat())}</p>"
        )
        block.append('<svg viewBox="0 0 960 320" role="img" aria-label="身体の三面図">')
        for view_index, (horizontal, vertical) in enumerate(views):
            left = view_index * 320
            block.append(
                f'<g transform="translate({left},0)"><text x="20" y="24">'
                f"{horizontal.upper()}–{vertical.upper()} 面</text>"
            )
            block.append(
                '<line class="axis" x1="35" y1="280" x2="285" y2="280"/>'
                '<line class="axis" x1="35" y1="280" x2="35" y2="45"/>'
            )
            block.append(
                f'<text x="265" y="302">+{horizontal.upper()}</text>'
                f'<text x="12" y="48">+{vertical.upper()}</text>'
            )

            def point(
                p: Vector3, horizontal: str = horizontal, vertical: str = vertical
            ) -> tuple[float, float]:
                return (
                    160 + (float(getattr(p, horizontal)) - centers[horizontal]) * scale,
                    160 - (float(getattr(p, vertical)) - centers[vertical]) * scale,
                )

            for joint in model.joints:
                x, y = point(world[joint.joint_id])
                if joint.parent_joint_id is not None:
                    px, py = point(world[joint.parent_joint_id])
                    block.append(
                        f'<line class="bone" x1="{px:.6f}" y1="{py:.6f}" '
                        f'x2="{x:.6f}" y2="{y:.6f}"/>'
                    )
                block.append(
                    f'<circle class="joint" cx="{x:.6f}" cy="{y:.6f}" r="4">'
                    f"<title>{escape(joint.joint_id)}</title></circle>"
                )
            for effector in model.end_effectors:
                x, y = point(end[effector.end_effector_id])
                px, py = point(world[effector.joint_id])
                block.append(
                    f'<line class="effector" x1="{px:.6f}" y1="{py:.6f}" '
                    f'x2="{x:.6f}" y2="{y:.6f}"><title>'
                    f"{escape(effector.end_effector_id)}</title></line>"
                )
            block.append("</g>")
        block.append("</svg><details><summary>表情などの値と採用情報</summary><pre>")
        block.extend(
            f"{escape(value.channel.value)}: {value.value:.6f}\n" for value in frame.channel_values
        )
        block.append(f"採用参照: {escape(', '.join(frame.applied_overlay_refs))}\n")
        block.append(f"不採用参照: {escape(', '.join(frame.degraded_overlay_refs))}\n")
        block.append("</pre></details></section>")
        value = "".join(block)
        total += len(value.encode("utf-8"))
        if total > max_bytes:
            raise ValueError("姿勢表示の書出し容量が上限を超えています")
        parts.append(value)
    parts.append("""<p class="muted">これは記録の可視化です。
描画先への適用や人間による品質評価の合格を意味しません。</p>
</main><script>
const frames = [...document.querySelectorAll('.pose')];
const seek = document.getElementById('seek');
const play = document.getElementById('play');
const position = document.getElementById('position');
let timer = null;
function stop(){clearTimeout(timer); timer=null; play.textContent='再生';}
function show(index){frames.forEach((f,i)=>{f.hidden=i!==index;});
seek.value=index; position.textContent=`${index+1} / ${frames.length}`;}
function advance(){const index=Number(seek.value);
if(index>=frames.length-1){stop();return;}
const delay=Number(frames[index+1].dataset.offset)-Number(frames[index].dataset.offset);
timer=setTimeout(()=>{show(index+1);advance();},Math.max(0,delay));}
seek.addEventListener('input',()=>{stop();show(Number(seek.value));});
play.addEventListener('click',()=>{if(timer!==null){stop();return;}
if(Number(seek.value)===frames.length-1){show(0);}play.textContent='一時停止';advance();});
</script></html>""")
    result = "".join(parts)
    if len(result.encode("utf-8")) > max_bytes:
        raise ValueError("姿勢表示の書出し容量が上限を超えています")
    return result
