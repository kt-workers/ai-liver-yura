from __future__ import annotations

import argparse
import time
from pathlib import Path

from .host_runtime import HostTransitionResult, HostTransitionStatus
from .runtime_console import RuntimeConsole, VisibleSubprocessLocalRunner

_CI_RECHECK_INITIAL_SECONDS = 60.0
_CI_RECHECK_MAX_SECONDS = 300.0
_MAX_IDENTICAL_COMPLETED = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Loop Engineering Mission runtime.")
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--validate-installation",
        action="store_true",
        help="Validate the control-plane package without observing or mutating external systems.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one bounded transition instead of the continuous Mission runtime.",
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
    runner = VisibleSubprocessLocalRunner(console)
    mode = "once" if arguments.once else "continuous"
    console.event(f"START mode={mode}")
    console.event(f"log: {console.path}")

    ci_wait_seconds = _CI_RECHECK_INITIAL_SECONDS
    previous_completed: tuple[str, int | None, int | None, str | None] | None = None
    identical_completed = 0
    transition_number = 0

    try:
        while True:
            transition_number += 1
            console.event(f"transition {transition_number}: begin")
            result = run_actual_host_transition(root=root, local_runner=runner)
            console.event(
                f"transition {transition_number}: "
                f"{result.status.value} detail={result.detail}"
            )

            if arguments.once:
                print(result.as_json())
                return _exit_code(result)

            if result.status is HostTransitionStatus.COMPLETED:
                completed_key = (
                    result.detail,
                    result.work_issue,
                    result.pr_number,
                    result.head_sha,
                )
                if completed_key == previous_completed:
                    identical_completed += 1
                else:
                    previous_completed = completed_key
                    identical_completed = 1
                if identical_completed >= _MAX_IDENTICAL_COMPLETED:
                    blocked = HostTransitionResult(
                        HostTransitionStatus.INTERVENTION_REQUIRED,
                        "NO_PROGRESS_GUARD",
                        result.work_issue,
                        result.pr_number,
                        result.head_sha,
                    )
                    console.event("NO_PROGRESS_GUARD: identical completed transition repeated")
                    print(blocked.as_json())
                    return 3
                ci_wait_seconds = _CI_RECHECK_INITIAL_SECONDS
                console.event("continue: fresh observe")
                continue

            previous_completed = None
            identical_completed = 0

            if (
                result.status is HostTransitionStatus.YIELD_EXTERNAL
                and result.detail == "CI_PENDING"
            ):
                console.event(
                    f"CI_PENDING: auto-resume in {int(ci_wait_seconds)}s"
                )
                time.sleep(ci_wait_seconds)
                ci_wait_seconds = min(
                    ci_wait_seconds * 2,
                    _CI_RECHECK_MAX_SECONDS,
                )
                continue

            print(result.as_json())
            return _exit_code(result)
    except KeyboardInterrupt:
        console.event("STOP requested by operator")
        return 130


def _exit_code(result: HostTransitionResult) -> int:
    if result.status is HostTransitionStatus.COMPLETED:
        return 0
    if result.status is HostTransitionStatus.YIELD_EXTERNAL:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
