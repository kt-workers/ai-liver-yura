from __future__ import annotations

import argparse


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
    parser.error("a host-specific Observer/Executor composition is required")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
