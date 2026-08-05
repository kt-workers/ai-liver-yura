from __future__ import annotations

import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = LAB_ROOT.parents[1]
for import_root in (LAB_ROOT, PROJECT_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

import server as lab_server  # noqa: E402


def main() -> None:
    lab_server.main()


if __name__ == "__main__":
    main()
