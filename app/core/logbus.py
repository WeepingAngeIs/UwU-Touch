"""Activity log: writes to the database and notifies listeners (the UI)."""
from __future__ import annotations

import logging
import threading

from .storage import Storage, now_iso

CATEGORIES = ["Recording", "Playback", "Discord", "Scheduler", "System"]

_pylog = logging.getLogger("novamacrohub")


class LogBus:
    def __init__(self, storage: Storage | None):
        self.storage = storage
        self._listeners = []
        self._lock = threading.Lock()

    def subscribe(self, fn):
        with self._lock:
            self._listeners.append(fn)

    def log(self, category: str, message: str, level: str = "info"):
        entry = {"ts": now_iso(), "category": category, "level": level, "message": message}
        _pylog.log(logging.ERROR if level == "error" else logging.INFO, "[%s] %s", category, message)
        if self.storage is not None:
            try:
                self.storage.add_log(category, level, message, ts=entry["ts"])
            except Exception:
                _pylog.exception("could not write log")
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                _pylog.exception("log listener failed")

    def info(self, category, message):
        self.log(category, message, "info")

    def warn(self, category, message):
        self.log(category, message, "warning")

    def error(self, category, message):
        self.log(category, message, "error")
