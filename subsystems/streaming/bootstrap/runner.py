"""One-shot runner for Core-independent process verification."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path

from app.integrations.streaming import CURRENT_STREAMING_API_VERSION
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.bootstrap.composition_root import (
    build_streaming_subsystem,
)
from subsystems.streaming.config import (
    EnvironmentSecretProvider,
    load_streaming_subsystem_config,
)


async def run_check(
    api: StreamingSubsystemApi | None = None,
    *,
    config_path: str | Path | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Print one deterministic health line and terminate."""

    if api is None:
        secrets = EnvironmentSecretProvider()
        config = load_streaming_subsystem_config(
            config_path,
            secret_provider=secrets,
        )
        subsystem = build_streaming_subsystem(
            config=config,
            secret_provider=secrets,
        )
    else:
        subsystem = api
    status = await subsystem.get_status()
    health = await subsystem.get_health()
    healthy = str(health.healthy).lower()
    output(
        "streaming-subsystem "
        f"status={status.value} "
        f"healthy={healthy} "
        f"api_version={CURRENT_STREAMING_API_VERSION}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the explicitly requested one-shot mode."""

    parser = argparse.ArgumentParser(prog="python -m subsystems.streaming")
    parser.add_argument(
        "--check",
        action="store_true",
        help="build the process shell, print health, and exit",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Streaming Subsystem YAML path",
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    return asyncio.run(run_check(config_path=args.config))
