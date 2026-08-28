from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Loop Engineering transition.")
    parser.add_argument("--version", action="store_true")
    arguments = parser.parse_args()
    if arguments.version:
        print("tools.loop_engine 1")
        return 0
    parser.error("a host-specific Observer/Executor composition is required")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
