"""信頼済みの起動設定から、実際の製品ソースの出典を確定する。"""

import subprocess
from pathlib import Path

from .contracts import ProductionTargetProvenance


def capture_production_provenance(
    repository: Path,
    source_paths: tuple[str, ...],
    module_contract_ids: tuple[str, ...],
    role_schema_ids: tuple[str, ...],
) -> ProductionTargetProvenance:
    """入力データにコマンドを含めず、未記録の製品変更をcommit済みと表示しない。"""
    if not source_paths or any(
        not name
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or name.startswith(("-", ":"))
        for name in source_paths
    ):
        raise ValueError("製品ソースの相対パスが必要です")

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode:
            raise ValueError("製品ソースの出典を確認できません")
        return result.stdout.strip()

    head = git("rev-parse", "HEAD")
    branch = git("symbolic-ref", "--short", "HEAD")
    for path in source_paths:
        if not git("ls-tree", "--name-only", "HEAD", "--", path):
            raise ValueError("製品ソースがcommitに存在しません")
    if git("status", "--porcelain", "--untracked-files=all", "--", *source_paths):
        raise ValueError("製品ソースに未記録の変更があります")
    if git("rev-parse", "HEAD") != head:
        raise ValueError("出典確認中に製品のHEADが変化しました")
    return ProductionTargetProvenance(head, branch, module_contract_ids, role_schema_ids)
