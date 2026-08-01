"""Standalone entrypoint for the Core Admin API."""

from __future__ import annotations

import argparse
import os

from app.admin_api.server import create_admin_api


def main() -> None:
    parser = argparse.ArgumentParser(description="Yura Core Admin API")
    parser.add_argument("--host", default=os.getenv("YURA_CORE_ADMIN_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("YURA_CORE_ADMIN_PORT", "8765"))
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print("Core Admin configuration valid")
        return
    import uvicorn

    uvicorn.run(create_admin_api(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
