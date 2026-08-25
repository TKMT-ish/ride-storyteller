"""Dependency-free request throttling for the public synthetic demo."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic


@dataclass
class FixedWindowRateLimiter:
    """Bound requests within one process without trusting client headers.

    Gunicorn workers do not share this state.  The Cloud Run service therefore
    combines this per-worker guard with bounded workers, concurrency, and a
    service-level maximum of one instance.
    """

    max_requests: int
    window_seconds: float
    clock: Callable[[], float] = monotonic
    _window_started_at: float = field(init=False, repr=False)
    _request_count: int = field(default=0, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_requests < 1:
            raise ValueError("max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_started_at = self.clock()

    def allow(self) -> tuple[bool, int]:
        """Return whether the request is allowed and a Retry-After value."""

        with self._lock:
            now = self.clock()
            elapsed = now - self._window_started_at
            if elapsed < 0 or elapsed >= self.window_seconds:
                self._window_started_at = now
                self._request_count = 0
                elapsed = 0
            if self._request_count >= self.max_requests:
                retry_after = max(1, math.ceil(self.window_seconds - elapsed))
                return False, retry_after
            self._request_count += 1
            return True, 0
