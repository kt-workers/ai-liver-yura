from __future__ import annotations

from threading import Event, Lock, Thread
from time import monotonic, sleep

from gui.body_pose_lab.application import BodyPoseLabApplicationService


class BodyPoseLabTickLoop:
    """Lab Applicationを一定周期で進めるThread lifecycle。"""

    def __init__(
        self,
        application: BodyPoseLabApplicationService,
    ) -> None:
        if not isinstance(application, BodyPoseLabApplicationService):
            raise TypeError("application must be BodyPoseLabApplicationService")
        self._application = application
        self._stop_requested = Event()
        self._lifecycle_lock = Lock()
        self._thread: Thread | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            self._stop_requested.clear()
            self._thread = Thread(
                target=self._run,
                name="body-pose-lab-tick",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be a number")
        if timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds must be greater than zero")
        with self._lifecycle_lock:
            thread = self._thread
            self._thread = None
            self._stop_requested.set()
        if thread is not None:
            thread.join(timeout=float(timeout_seconds))

    def _run(self) -> None:
        interval = 1.0 / self._application.tick_hz
        next_tick = monotonic()
        while not self._stop_requested.is_set():
            started = monotonic()
            try:
                self._application.tick_once(dt_seconds=interval)
            except Exception as error:  # pragma: no cover - safety boundary
                self._last_error = f"{type(error).__name__}: {error}"[:240]
            else:
                self._last_error = None
            next_tick = max(next_tick + interval, started + interval)
            remaining = next_tick - monotonic()
            if remaining > 0.0:
                sleep(remaining)
