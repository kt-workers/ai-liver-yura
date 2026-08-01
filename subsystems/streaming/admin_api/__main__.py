"""Independent CLI for the Streaming Subsystem Admin API."""

from __future__ import annotations

import argparse
import os

import uvicorn

from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem
from subsystems.streaming.config import (
    EnvironmentSecretProvider,
    load_streaming_subsystem_config,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8781


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Streaming Subsystem standalone Admin API")
    parser.add_argument(
        "--host",
        default=os.getenv("STREAMING_SUBSYSTEM_ADMIN_API_HOST", DEFAULT_HOST),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("STREAMING_SUBSYSTEM_ADMIN_API_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_streaming_subsystem_config(
        args.config,
        secret_provider=EnvironmentSecretProvider(),
    )
    subsystem = build_streaming_subsystem(
        config=config,
        secret_provider=EnvironmentSecretProvider(),
    )
    if args.check:
        print(f"streaming-subsystem-admin host={args.host} port={args.port} configuration=valid")
        return 0
    app = create_streaming_admin_api(subsystem)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
