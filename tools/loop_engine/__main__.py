from __future__ import annotations

import argparse

from .host_runtime import HostTransitionStatus


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Loop Engineering transition.")
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--validate-installation",
        action="store_true",
        help="Validate the control-plane package without observing or mutating external systems.",
    )
    arguments = parser.parse_args()
    if arguments.version:
        print("tools.loop_engine 1")
        return 0
    if arguments.validate_installation:
        print("LOOP_ENGINE_INSTALLATION=PASS")
        return 0

    from .host_entrypoint import run_actual_host_transition

    result = run_actual_host_transition()
    print(result.as_json())
    if result.status is HostTransitionStatus.COMPLETED:
        return 0
    if result.status is HostTransitionStatus.YIELD_EXTERNAL:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
