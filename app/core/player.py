"""Macro playback on a background thread.

Timing: every action's fire time is computed from the start of the loop
(start + sum of delays / speed), so small sleep errors never add up over a long
macro. Emergency stop sets an Event that is checked between every action and
inside every wait; all held keys and buttons are released immediately after.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable

from .models import Action, Macro, PlaybackSettings


class _HighResTimer:
    """Asks Windows for 1 ms timer resolution while playing (default is ~15.6 ms)."""

    def __enter__(self):
        self.ok = False
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
                self.ok = True
            except Exception:
                pass
        return self

    def __exit__(self, *exc):
        if self.ok:
            import ctypes
            ctypes.windll.winmm.timeEndPeriod(1)


class Player:
    def __init__(self, driver_factory: Callable, discord_sender: Callable | None = None,
                 on_progress: Callable | None = None, on_state: Callable | None = None,
                 on_log: Callable | None = None):
        self.driver_factory = driver_factory
        self.discord_sender = discord_sender  # fn(params) -> (ok, error_text)
        self.on_progress = on_progress or (lambda loop, step, total: None)
        self.on_state = on_state or (lambda playing, reason: None)
        self.on_log = on_log or (lambda level, msg: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.driver = None
        self._started_at = None
        self._elapsed_final = 0.0
        self.last_error = None

    def elapsed(self):
        if self._started_at is None:
            return self._elapsed_final
        return max(0.0, time.perf_counter() - self._started_at)

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def play(self, macro: Macro, settings: PlaybackSettings | None = None, start_delay: float = 0.0) -> bool:
        with self._lock:
            if self.playing:
                return False
            if not macro.actions:
                raise ValueError("This macro has no steps yet.")
            self._elapsed_final = 0.0
            self._started_at = time.perf_counter()
            self._stop = threading.Event()
            actions = [a.clone(keep_id=True) for a in macro.actions]
            settings = settings or macro.playback
            self._thread = threading.Thread(target=self._run, args=(macro.name, actions, settings, start_delay, self._stop),
                                            name="macro-player", daemon=True)
            self._thread.start()
            return True

    def stop(self, wait: float = 2.0):
        """Emergency stop. Safe to call from any thread, any number of times."""
        self._stop.set()
        drv = self.driver
        if drv is not None:
            try:
                drv.release_all()
            except Exception:
                pass
        t = self._thread
        if t is not None and t is not threading.current_thread() and wait:
            t.join(wait)

    # ---- internals ----------------------------------------------------
    def _sleep_until(self, target: float, stop: threading.Event) -> bool:
        """Wait until perf_counter() >= target. Returns False if stopped."""
        while True:
            if stop.is_set():
                return False
            remaining = target - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > 0.004:
                stop.wait(min(remaining - 0.002, 0.05))
            else:
                time.sleep(0)  # final ~2 ms: spin for accuracy

    def _run(self, name, actions, settings: PlaybackSettings, start_delay, stop):
        reason = "finished"
        self.last_error = None
        try:
            self.driver = self.driver_factory()
        except Exception as e:
            self.last_error = str(e)
            self.on_log("error", f"Could not start input driver: {e}")
            self._elapsed_final = self.elapsed()
            self._started_at = None
            self.on_state(False, "error")
            return
        drv = self.driver
        speed = settings.speed if settings.speed > 0 else 1.0
        if settings.repeat_mode == "forever":
            loops = None
        elif settings.repeat_mode == "count":
            loops = max(1, settings.repeat_count)
        else:
            loops = 1
        self.on_state(True, "started")
        self.on_log("info", f"Playing '{name}' ({len(actions)} steps, "
                    f"{'until stopped' if loops is None else f'{loops}x'}, speed {speed:g}x)")
        loop = 0
        try:
            with _HighResTimer():
                if start_delay > 0 and not self._sleep_until(time.perf_counter() + start_delay, stop):
                    reason = "stopped"
                    return
                while loops is None or loop < loops:
                    loop += 1
                    t0 = time.perf_counter()
                    elapsed = 0.0
                    last_progress = 0.0
                    for i, a in enumerate(actions):
                        elapsed += a.delay
                        if not self._sleep_until(t0 + elapsed / speed, stop):
                            reason = "stopped"
                            return
                        if stop.is_set():
                            reason = "stopped"
                            return
                        if a.enabled:
                            self._execute(a, drv, stop)
                        now = time.perf_counter()
                        if now - last_progress > 0.05 or i == len(actions) - 1:
                            last_progress = now
                            self.on_progress(loop, i, len(actions))
                    drv.release_all()
                    if loops is not None and loop >= loops:
                        break
                    if settings.loop_delay > 0:
                        if not self._sleep_until(time.perf_counter() + settings.loop_delay, stop):
                            reason = "stopped"
                            return
                    if stop.is_set():
                        reason = "stopped"
                        return
        except Exception as e:
            reason = "error"
            self.last_error = str(e)
            self.on_log("error", f"Playback error: {e}")
        finally:
            try:
                drv.release_all()
            finally:
                self.driver = None
                if reason == "stopped":
                    self.on_log("info", f"Playback of '{name}' stopped (loop {loop}). All keys released.")
                elif reason == "finished":
                    self.on_log("info", f"Finished playing '{name}' ({loop} loop{'s' if loop != 1 else ''}).")
                self._elapsed_final = self.elapsed()
                self._started_at = None
                self.on_state(False, reason)

    def _execute(self, a: Action, drv, stop):
        p = a.params
        t = a.type
        if t == "key_down":
            drv.key_down(p["key"])
        elif t == "key_up":
            drv.key_up(p["key"])
        elif t == "key_tap":
            drv.key_down(p["key"])
            self._sleep_until(time.perf_counter() + float(p.get("hold_ms", 50)) / 1000, stop)
            drv.key_up(p["key"])
        elif t == "mouse_move":
            drv.mouse_move(p["x"], p["y"])
        elif t == "mouse_down":
            drv.mouse_button(p.get("button", "left"), True, p.get("x"), p.get("y"))
        elif t == "mouse_up":
            drv.mouse_button(p.get("button", "left"), False, p.get("x"), p.get("y"))
        elif t == "mouse_click":
            for n in range(max(1, int(p.get("count", 1)))):
                if stop.is_set():
                    return
                drv.mouse_button(p.get("button", "left"), True, p.get("x"), p.get("y"))
                time.sleep(0.03)
                drv.mouse_button(p.get("button", "left"), False, p.get("x"), p.get("y"))
                time.sleep(0.05)
        elif t == "scroll":
            drv.scroll(p.get("x"), p.get("y"), int(p.get("dx", 0)), int(p.get("dy", 0)))
        elif t == "type_text":
            drv.type_text(p.get("text", ""), should_stop=stop.is_set)
        elif t == "discord":
            if self.discord_sender is None:
                self.on_log("error", "Discord step skipped: Discord is not set up.")
                return
            ok, err = self.discord_sender(p)
            if not ok:
                self.on_log("error", f"Discord step failed: {err}")
        elif t == "wait":
            pass
