"""模擬ゲームの独立進行を製品の実行基盤で確認し、証拠を書き出す。"""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from app.subsystems.validation.contracts import Gate, LabMode, LabPolicy, LabRunSpec
from app.subsystems.validation.game_skill import game_fixture, game_target
from app.subsystems.validation.provenance import capture_production_provenance
from app.subsystems.validation.runtime import ValidationRunner


async def execute(repository: Path, output: Path, repeat_count: int) -> int:
    provenance = capture_production_provenance(
        repository,
        ("app/subsystems/game_skill", "app/domain/contracts", "app/domain/llm"),
        ("game_skill_runtime_contracts.md",),
        (),
    )
    policy = LabPolicy(10, 8, 128, 1_000_000, 5.0, 1)
    runner = ValidationRunner((game_target(provenance),), policy)
    fixture = game_fixture()
    try:
        result = await runner.run(
            LabRunSpec(
                "game-independent-loop",
                "game-realtime",
                LabMode.ISOLATION,
                "game_skill",
                "1",
                fixture.scenario_id,
                fixture.fixture_revision,
                (),
                repeat_count,
                datetime.now(timezone.utc),
            ),
            fixture,
        )
        encoded = result.export_json(policy.max_export_bytes)
        markdown = result.export_markdown(policy.max_export_bytes)
        output.mkdir(parents=True, exist_ok=True)
        # 既存の証拠を黙って上書きしない。
        with (output / "result.json").open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        with (output / "result.md").open("x", encoding="utf-8") as stream:
            stream.write(markdown)
        print(f"検証結果: {result.status.value} / {result.machine_gate.value}")
        print(f"証拠の保存先: {output}")
        return 0 if result.machine_gate is Gate.PASS else 1
    finally:
        await runner.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="製品のゲーム実行基盤で独立進行を検証します")
    parser.add_argument("--output", type=Path, required=True, help="新しい証拠の保存先")
    parser.add_argument("--repeat", type=int, default=1, help="検証の繰返し回数（1〜10）")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    try:
        return asyncio.run(execute(repository, args.output, args.repeat))
    except (OSError, ValueError):
        print("検証の開始または証拠の保存に失敗しました。出典と保存先を確認してください")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
