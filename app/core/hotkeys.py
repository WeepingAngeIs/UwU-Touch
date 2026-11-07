"""Global hotkeys that work even when another window (the game) has focus."""
from __future__ import annotations

import threading
from typing import Callable

from . import keynames
from .recorder import key_name_from_pynput


class HotkeyManager:
    def __init__(self, on_log: Callable | None = None):
        self._bindings: dict[str, tuple[frozenset, str, Callable, bool]] = {}
        self._held: set[str] = set()
        self._listener = None
        self._lock = threading.Lock()
        self.on_log = on_log or (lambda level, msg: None)

    def bind(self, action: str, hotkey: str, callback: Callable, allow_injected=False):
        """Register (or replace) a hotkey. Raises ValueError for invalid text."""
        if not hotkey:
            with self._lock:
                self._bindings.pop(action, None)
            return
        mods, main = keynames.parse_hotkey(hotkey)
        with self._lock:
            for other, (m2, k2, _, _) in self._bindings.items():
                if other != action and m2 == mods and k2 == main:
                    raise ValueError(f"{keynames.hotkey_label(hotkey)} is already used for another hotkey")
            self._bindings[action] = (mods, main, callback, allow_injected)

    def main_keys(self) -> set[str]:
        with self._lock:
            return {b[1] for b in self._bindings.values()}

    def modifiers(self) -> set[str]:
        with self._lock:
            out = set()
            for b in self._bindings.values():
                out |= set(b[0])
            return out

    def start(self):
        if self._listener is not None:
            return
        try:
            from pynput import keyboard
            self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            self._listener = None
            self.on_log("error", f"Global hotkeys unavailable: {e}")

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    # ---- matching -----------------------------------------------------
    def _press(self, key, injected=False, *args):
        self.handle(key_name_from_pynput(key), True, bool(injected))

    def _release(self, key, injected=False, *args):
        self.handle(key_name_from_pynput(key), False, bool(injected))

    def handle(self, name: str | None, down: bool, injected: bool = False):
        """Process one key event. Returns the triggered action name or None."""
        if not name:
            return None
        if not down:
            self._held.discard(name)
            return None
        repeat = name in self._held
        self._held.add(name)
        if repeat:
            return None
        active_mods = {keynames.MODIFIER_GROUP[k] for k in self._held if k in keynames.MODIFIER_GROUP}
        with self._lock:
            bindings = list(self._bindings.items())
        # A hotkey fires when its modifiers are held (extra held modifiers are
        # allowed, so Emergency Stop still works while a macro holds Shift).
        # If several match, the one with the most modifiers wins.
        best = None
        for action, (mods, main, cb, allow_injected) in bindings:
            if name == main and set(mods) <= active_mods:
                if injected and not allow_injected:
                    continue
                if best is None or len(mods) > len(best[1]):
                    best = (action, mods, cb)
        if best is None:
            return None
        action, _, cb = best
        try:
            cb()
        except Exception as e:
            self.on_log("error", f"Hotkey '{action}' failed: {e}")
        return action
