"""Glue between the core modules and the interface (Qt signals for thread safety)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .core import discord_client as dc
from .core.discord_client import DiscordClient, FloodGuard, SendResult
from .core.hotkeys import HotkeyManager
from .core.inputs import make_driver
from .core.logbus import LogBus
from .core.models import Macro, PlaybackSettings
from .core.player import Player
from .core.recorder import Recorder
from .core.scheduler import Scheduler
from .core.secrets_store import SecretStore
from .core.storage import Storage, data_dir

APP_NAME = "NovaMacroHub"


class Engine(QObject):
    log_entry = Signal(dict)
    state_changed = Signal()
    playback_progress = Signal(int, int, int)
    recording_event = Signal(int)
    schedules_changed = Signal()
    notify = Signal(str, str)
    hotkey = Signal(str)

    def __init__(self, storage: Storage | None = None, secrets: SecretStore | None = None, start_threads=True):
        super().__init__()
        self.storage = storage or Storage()
        self.secrets = secrets or SecretStore(data_dir() / "secrets.json")
        self.log = LogBus(self.storage)
        self.log.subscribe(self.log_entry.emit)
        self.flood = FloodGuard(int(self.storage.get_setting("flood_per_minute") or 10))
        self.discord = DiscordClient(flood_guard=self.flood)
        self.player = Player(driver_factory=lambda: make_driver(self.storage.get_setting("input_mode")),
                             discord_sender=self._discord_step,
                             on_progress=self.playback_progress.emit,
                             on_state=self._on_play_state,
                             on_log=lambda lvl, m: self.log.log("Playback", m, "error" if lvl == "error" else "info"))
        self.recorder: Recorder | None = None
        self.now_playing = ""
        self.hotkeys = HotkeyManager(on_log=lambda lvl, m: self.log.log("System", m, lvl))
        self.scheduler = Scheduler(self.storage, self.log, send_message=self._scheduled_send,
                                   run_macro=self._scheduled_macro,
                                   on_change=self.schedules_changed.emit,
                                   on_failure=self.notify.emit)
        self.scheduler.messages_paused = bool(self.storage.get_setting("messages_paused", False))
        try:
            self.storage.trim_logs(keep=20000)
        except Exception:
            pass
        if start_threads:
            self.apply_hotkeys()
            self.hotkeys.start()
            self.scheduler.start()
            self.log.info("System", "Nova Macro Hub started.")

    def shutdown(self):
        try:
            self.player.stop(wait=1)
        finally:
            if self.recorder and self.recorder.recording:
                self.recorder.stop()
            self.hotkeys.stop()
            self.scheduler.shutdown()
            self.log.info("System", "Nova Macro Hub closed.")

    # ---- hotkeys ------------------------------------------------------
    def apply_hotkeys(self):
        """(Re)bind hotkeys from settings. Returns list of error strings."""
        errors = []
        s = self.storage
        binds = [
            ("stop", s.get_setting("hotkey_stop"), self._hotkey_emergency, True),
            ("record", s.get_setting("hotkey_record"), lambda: self.hotkey.emit("record"), False),
            ("pause", s.get_setting("hotkey_pause"), lambda: self.hotkey.emit("pause"), False),
            ("play", s.get_setting("hotkey_play"), lambda: self.hotkey.emit("play"), False),
        ]
        self.hotkeys._bindings.clear()
        for name, text, cb, inj in binds:
            try:
                self.hotkeys.bind(name, text, cb, allow_injected=inj)
            except ValueError as e:
                errors.append(f"{name}: {e}")
                self.log.error("System", f"Hotkey for {name} not set: {e}")
        return errors

    def _hotkey_emergency(self):
        # Runs on the keyboard-listener thread: stop immediately, then tell the UI.
        self.emergency_stop(source="hotkey")
        self.hotkey.emit("stop")

    # ---- playback -----------------------------------------------------
    def play(self, macro: Macro, settings: PlaybackSettings | None = None, countdown: float = 0.0) -> bool:
        if self.recorder and self.recorder.recording:
            raise RuntimeError("Stop recording before playing.")
        self.now_playing = macro.name
        return self.player.play(macro, settings, start_delay=countdown)

    def emergency_stop(self, source="button"):
        was_playing = self.player.playing
        self.player.stop(wait=0)
        if any(s["enabled"] for s in self.storage.list_schedules("macro")):
            self.scheduler.macros_paused = True
        self.log.warn("Playback", f"EMERGENCY STOP ({source}). "
                      + ("Playback halted and all keys released." if was_playing else "Nothing was playing."))
        self.state_changed.emit()

    def resume_macro_schedules(self):
        self.scheduler.macros_paused = False
        self.log.info("Scheduler", "Macro schedules resumed.")
        self.state_changed.emit()

    def _on_play_state(self, playing, reason):
        if reason == "error" and self.player.last_error:
            self.notify.emit("Playback error", self.player.last_error)
        self.state_changed.emit()

    # ---- recording ----------------------------------------------------
    def start_recording(self) -> Recorder:
        if self.player.playing:
            raise RuntimeError("Stop playback before recording.")
        s = self.storage
        rec = Recorder(record_moves=bool(s.get_setting("record_mouse_moves")),
                       move_interval_ms=int(s.get_setting("mouse_move_interval_ms")),
                       ignore_keys=self.hotkeys.main_keys(),
                       on_event=lambda a, n: self.recording_event.emit(n))
        rec.hotkey_modifiers = self.hotkeys.modifiers()
        rec.start()
        self.recorder = rec
        self.log.info("Recording", "Recording started.")
        self.state_changed.emit()
        return rec

    def stop_recording(self, trim_clicks: int = 0):
        rec = self.recorder
        if not rec or not rec.recording:
            return []
        actions = rec.stop(trim_clicks=trim_clicks)
        self.log.info("Recording", f"Recording stopped: {len(actions)} steps, {sum(a.delay for a in actions):.2f}s.")
        self.state_changed.emit()
        return actions

    @property
    def recording(self):
        return bool(self.recorder and self.recorder.recording)

    # ---- discord ------------------------------------------------------
    def bot_token(self):
        return self.secrets.get("bot_token")

    def send_to_target(self, target_id, content, allow_everyone=False, nonce=None) -> SendResult:
        t = self.storage.get_target(target_id) if target_id else None
        if not t:
            return SendResult(False, "No Discord channel chosen (or it was deleted).")
        self.flood.per_minute = int(self.storage.get_setting("flood_per_minute") or 10)
        if t["kind"] == "webhook":
            url = self.secrets.get(f"webhook:{t['id']}")
            if not url:
                return SendResult(False, f"The webhook URL for '{t['name']}' is missing. Edit the channel and paste it again.")
            return self.discord.send_webhook(url, content, allow_everyone)
        return self.discord.send_bot(self.bot_token(), t["channel_id"], content, allow_everyone, nonce=nonce)

    def _discord_step(self, params):
        res = self.send_to_target(params.get("target_id"), params.get("message", ""),
                                  bool(params.get("allow_everyone")),
                                  nonce=dc.make_nonce("step", params.get("target_id"), params.get("message"),
                                                      threading.get_ident(), time.time()))
        if res.ok:
            self.log.info("Discord", f"Macro step sent to {params.get('target_name', 'Discord')}.")
        return res.ok, res.error

    def _scheduled_send(self, s, slot):
        return self.send_to_target(s["target_id"], s["message"], bool(s["allow_everyone"]),
                                   nonce=dc.make_nonce("sched", s["id"], slot))

    def _scheduled_macro(self, s):
        if self.player.playing:
            return False, "another macro is already playing"
        if self.recording:
            return False, "recording is in progress"
        m = self.storage.load_macro(s["macro_id"]) if s.get("macro_id") else None
        if not m:
            return False, "the macro was deleted"
        if not m.actions:
            return False, "the macro has no steps"
        try:
            self.now_playing = m.name
            return bool(self.player.play(m, m.playback)), "ok"
        except Exception as e:
            return False, str(e)

    def test_target(self, target_id, text="✅ Nova Macro Hub test message — this channel is set up!") -> SendResult:
        res = self.send_to_target(target_id, text)
        self.storage.update_target(target_id, last_test_ok=1 if res.ok else 0)
        t = self.storage.get_target(target_id)
        name = t["name"] if t else "channel"
        if res.ok:
            self.log.info("Discord", f"Test message sent to '{name}'.")
        else:
            self.log.error("Discord", f"Test message to '{name}' failed: {res.error}")
        return res

    # ---- misc ---------------------------------------------------------
    def set_messages_paused(self, paused: bool):
        self.scheduler.messages_paused = paused
        self.storage.set_setting("messages_paused", paused)
        self.log.info("Scheduler", "All Discord schedules paused." if paused else "Discord schedules resumed.")
        self.state_changed.emit()

    def set_autostart(self, enabled: bool):
        if sys.platform != "win32":
            raise RuntimeError("Start with Windows only works on Windows.")
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        try:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" --minimized'
                else:
                    pyw = Path(sys.executable).with_name("pythonw.exe")
                    main = Path(__file__).resolve().parent.parent / "run.py"
                    cmd = f'"{pyw if pyw.exists() else sys.executable}" "{main}" --minimized'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
