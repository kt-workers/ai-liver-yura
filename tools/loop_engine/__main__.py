from __future__ import annotations

import argparse
from pathlib import Path

from .host_runtime import HostTransitionStatus
from .runtime_console import RuntimeConsole, VisibleSubprocessLocalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Loop Engineering transition.")
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--validate-installation",
        action="store_true",
        help="Validate the control-plane package without observing or mutating external systems.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed child-process output on stderr in addition to the persistent run log.",
    )
    arguments = parser.parse_args()
    if arguments.version:
        print("tools.loop_engine 1")
        return 0
    if arguments.validate_installation:
        print("LOOP_ENGINE_INSTALLATION=PASS")
        return 0

    from .host_entrypoint import run_actual_host_transition

    root = Path(__file__).resolve().parents[2]
    console = RuntimeConsole(root, verbose=arguments.verbose)
    console.event("START")
    console.event(f"log: {console.path}")
    console.event("preflight / GitHub observe: begin")
    result = run_actual_host_transition(
        root=root,
        local_runner=VisibleSubprocessLocalRunner(console),
    )
    console.event(f"RESULT status={result.status.value} detail={result.detail}")
    print(result.as_json())
    if result.status is HostTransitionStatus.COMPLETED:
        return 0
    if result.status is HostTransitionStatus.YIELD_EXTERNAL:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
