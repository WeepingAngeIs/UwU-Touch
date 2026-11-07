"""Global keyboard + mouse recorder (pynput listeners on background threads)."""
from __future__ import annotations

import threading
import time
from typing import Callable

from . import keynames
from .models import Action


def key_name_from_pynput(key) -> str | None:
    """Convert a pynput key to our key name using its virtual-key code."""
    vk = getattr(key, "vk", None)
    if vk is None:
        value = getattr(key, "value", None)
        vk = getattr(value, "vk", None)
    if vk is not None:
        return keynames.name_for_vk(int(vk))
    ch = getattr(key, "char", None)
    if ch:
        return ch.lower()
    name = getattr(key, "name", None)
    return name


def button_name(button) -> str:
    name = getattr(button, "name", str(button))
    return {"x1": "x1", "x2": "x2", "button8": "x1", "button9": "x2"}.get(name, name)


class Recorder:
    """Collects actions with exact delays. Pause time is excluded from delays.

    Feed events with the _on_* methods (pynput calls them; tests call them
    directly with explicit timestamps).
    """

    def __init__(self, record_moves=True, move_interval_ms=15, ignore_keys=None,
                 on_event: Callable | None = None, clock=time.perf_counter):
        self.record_moves = record_moves
        self.move_interval = max(0, move_interval_ms) / 1000.0
        self.ignore_keys = set(ignore_keys or [])
        self.on_event = on_event or (lambda action, count: None)
        self.clock = clock
        self.actions: list[Action] = []
        self._held: set[str] = set()
        self._held_buttons: set[str] = set()
        self._lock = threading.Lock()
        self._listeners = []
        self.recording = False
        self.paused = False
        self._start = 0.0
        self._last = 0.0
        self._paused_at = 0.0
        self._paused_total = 0.0
        self._last_move = -1.0
        self._last_pos = None
        self._ignored_down: set[str] = set()

    # ---- control ------------------------------------------------------
    def start(self, with_listeners=True):
        with self._lock:
            self.actions = []
            self._held.clear()
            self._held_buttons.clear()
            self._ignored_down.clear()
            self._start = self._last = self.clock()
            self._paused_total = 0.0
            self.paused = False
            self.recording = True
        if with_listeners:
            from pynput import keyboard, mouse
            kl = keyboard.Listener(on_press=self._kb_press, on_release=self._kb_release)
            ml = mouse.Listener(on_move=self._ms_move, on_click=self._ms_click, on_scroll=self._ms_scroll)
            kl.daemon = ml.daemon = True
            kl.start()
            ml.start()
            self._listeners = [kl, ml]

    def pause(self):
        with self._lock:
            if self.recording and not self.paused:
                self.paused = True
                self._paused_at = self.clock()

    def resume(self):
        with self._lock:
            if self.recording and self.paused:
                gap = self.clock() - self._paused_at
                self._paused_total += gap
                self._last += gap  # pause time never counts as a delay
                self.paused = False

    def stop(self, trim_clicks: int = 0) -> list[Action]:
        """Stop recording. `trim_clicks` removes that many final mouse clicks
        (e.g. the click on the app's own Stop button or tray menu)."""
        for l in self._listeners:
            try:
                l.stop()
            except Exception:
                pass
        self._listeners = []
        with self._lock:
            if self.paused:
                self.resume_no_lock()
            self.recording = False
            self._trim_clicks(trim_clicks)
            # Keys still held at stop: modifiers that belong to a hotkey are
            # dropped; anything else gets a release so playback never sticks.
            for key in list(self._held):
                if keynames.MODIFIER_GROUP.get(key) and self._is_hotkey_modifier(key):
                    for i in range(len(self.actions) - 1, -1, -1):
                        a = self.actions[i]
                        if a.type == "key_down" and a.params.get("key") == key:
                            if i + 1 < len(self.actions):
                                self.actions[i + 1].delay += a.delay
                            del self.actions[i]
                            break
                else:
                    self.actions.append(Action("key_up", 0.0, {"key": key}))
            for b in list(self._held_buttons):
                self.actions.append(Action("mouse_up", 0.0, {"button": b, **self._pos_dict()}))
            self._held.clear()
            self._held_buttons.clear()
            return list(self.actions)

    def _pos_dict(self):
        if self._last_pos:
            return {"x": int(self._last_pos[0]), "y": int(self._last_pos[1])}
        return {"x": 0, "y": 0}

    def _trim_clicks(self, n):
        """Remove the last n mouse_down/mouse_up pairs plus the mouse moves after
        the first removed click (moving to the Stop button)."""
        removed = 0
        while removed < n:
            idx = None
            for i in range(len(self.actions) - 1, -1, -1):
                if self.actions[i].type == "mouse_down":
                    idx = i
                    break
            if idx is None:
                break
            cut = idx
            while cut > 0 and self.actions[cut - 1].type == "mouse_move":
                cut -= 1
            del self.actions[cut:]
            self._held_buttons.clear()
            removed += 1

    def resume_no_lock(self):
        gap = self.clock() - self._paused_at
        self._paused_total += gap
        self._last += gap
        self.paused = False

    hotkey_modifiers: set = set()

    def _is_hotkey_modifier(self, key):
        return keynames.MODIFIER_GROUP.get(key) in self.hotkey_modifiers

    def elapsed(self) -> float:
        with self._lock:
            if not self.recording:
                return sum(a.delay for a in self.actions)
            now = self._paused_at if self.paused else self.clock()
            return now - self._start - self._paused_total

    # ---- event intake -------------------------------------------------
    def _add(self, type_, params, t=None):
        with self._lock:
            if not self.recording or self.paused:
                return
            t = self.clock() if t is None else t
            delay = max(0.0, t - self._last)
            self._last = t
            a = Action(type_, round(delay, 6), params)
            self.actions.append(a)
            count = len(self.actions)
        self.on_event(a, count)

    def key_event(self, key: str, down: bool, t=None):
        if not key:
            return
        if key in self.ignore_keys:
            if down:
                self._ignored_down.add(key)
            else:
                self._ignored_down.discard(key)
            return
        with self._lock:
            if not self.recording or self.paused:
                return
            if down:
                if key in self._held:
                    return  # Windows auto-repeat while held: record the press once
                self._held.add(key)
            else:
                if key not in self._held:
                    return  # release of a key pressed before recording started
                self._held.discard(key)
        self._add("key_down" if down else "key_up", {"key": key}, t)

    def move_event(self, x, y, t=None):
        if not self.record_moves:
            return
        t = self.clock() if t is None else t
        if self._last_pos == (x, y):
            return
        if self._last_move >= 0 and t - self._last_move < self.move_interval:
            return
        self._last_move = t
        self._last_pos = (x, y)
        self._add("mouse_move", {"x": int(x), "y": int(y)}, t)

    def click_event(self, x, y, button: str, down: bool, t=None):
        self._last_pos = (x, y)
        with self._lock:
            if not self.recording or self.paused:
                return
            if down:
                self._held_buttons.add(button)
            elif button in self._held_buttons:
                self._held_buttons.discard(button)
            else:
                return  # release of a click that started before recording
        self._add("mouse_down" if down else "mouse_up", {"button": button, "x": int(x), "y": int(y)}, t)

    def scroll_event(self, x, y, dx, dy, t=None):
        self._add("scroll", {"x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)}, t)

    # ---- pynput callbacks ---------------------------------------------
    def _kb_press(self, key, *args):
        self.key_event(key_name_from_pynput(key), True)

    def _kb_release(self, key, *args):
        self.key_event(key_name_from_pynput(key), False)

    def _ms_move(self, x, y, *args):
        self.move_event(x, y)

    def _ms_click(self, x, y, button, pressed, *args):
        self.click_event(x, y, button_name(button), pressed)

    def _ms_scroll(self, x, y, dx, dy, *args):
        self.scroll_event(x, y, dx, dy)
