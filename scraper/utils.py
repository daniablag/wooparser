from __future__ import annotations
import threading
import time
import logging
from typing import Callable
from rich.logging import RichHandler

_logger_initialized = False


def get_logger(name: str = "scraper") -> logging.Logger:
    global _logger_initialized
    if not _logger_initialized:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            datefmt="%H:%M:%S",
            handlers=[RichHandler(rich_tracebacks=True)],
        )
        _logger_initialized = True
    return logging.getLogger(name)


class RateLimiter:
    def __init__(self, rps: float) -> None:
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.perf_counter()
            delta = now - self._last
            wait_for = self.min_interval - delta
            if wait_for > 0:
                time.sleep(wait_for)
            self._last = time.perf_counter()
