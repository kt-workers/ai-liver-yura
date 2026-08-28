from __future__ import annotations

import subprocess
import sys


def test_cli_validates_installation_without_external_mutation() -> None:
    result = subprocess.run(
        (sys.executable, "-m", "tools.loop_engine", "--validate-installation"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == "LOOP_ENGINE_INSTALLATION=PASS\n"
