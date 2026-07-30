"""Module entrypoint for the Streaming Subsystem process shell."""

from subsystems.streaming.bootstrap.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
