"""Macro Recorder page: record, play and manage saved macros."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QProgressBar, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core import keynames
from ..core.models import PlaybackSettings, format_clock
from .common import button, card, confirm, error_box, info_box, muted, page_layout, row

MODES = [("replace", "Replace all steps"), ("append", "Add to the end"), ("insert", "Insert after selected timeline row")]


class RecorderPage(QWidget):
    request_minimize = Signal()
    request_restore = Signal()
    show_timeline = Signal()

    def __init__(self, engine, session):
        super().__init__()
        self.engine = engine
        self.session = session
        self.storage = engine.storage
        self._pending_insert_at = None
        self._countdown_left = 0
        self._countdown_action = None
        self._countdown_label = ""
        self._mode = "replace"
        lay = page_layout(self, "Macro Recorder",
                          "Record your keyboard and mouse, then fine-tune every step in the Timeline Editor.")

        # ---- macro picker
        top, tl = card()
        self.macro_cb = QComboBox()
        self.macro_cb.setMinimumWidth(260)
        self.macro_cb.activated.connect(self._pick_macro)
        tl.addLayout(row(QLabel("Macro:"), self.macro_cb,
                         button("New", self._new), button("Rename…", self._rename),
                         button("Delete", self._delete), None,
                         button("Import JSON…", self._import), button("Export JSON…", self._export)))
        self.macro_info = muted("")
        tl.addWidget(self.macro_info)
        lay.addWidget(top)

        grid = QGridLayout()
        grid.setSpacing(14)
        lay.addLayout(grid, 1)

        # ---- record card
        rc, rl = card("Record", "")
        self.hint = muted("")
        rl.addWidget(self.hint)
        self.clock = QLabel("00:00.00")
        self.clock.setObjectName("bigclock")
        self.status = QLabel("Ready")
        self.status.setObjectName("h2")
        self.count = muted("0 steps", wrap=False)
        rl.addLayout(row(self.clock, None, self.status))
        rl.addWidget(self.count)
        self.rec_b = button("● Record", self.start_record, kind="danger")
        self.pause_b = button("⏸ Pause", self.pause_record)
        self.resume_b = button("▶ Resume", self.resume_record)
        self.stop_b = button("■ Stop", lambda: self.stop_record("button"))
        self.save_b = button("💾 Save", self._save, kind="primary")
        rl.addLayout(row(self.rec_b, self.pause_b, self.resume_b, self.stop_b, None, self.save_b))
        f = QFormLayout()
        self.mode_cb = QComboBox()
        for k, label in MODES:
            self.mode_cb.addItem(label, k)
        f.addRow("When recording:", self.mode_cb)
        self.moves_cb = QCheckBox("Record mouse movement (not just clicks)")
        self.moves_cb.setChecked(bool(self.storage.get_setting("record_mouse_moves")))
        self.moves_cb.toggled.connect(lambda v: self.storage.set_setting("record_mouse_moves", v))
        f.addRow("", self.moves_cb)
        self.minimize_cb = QCheckBox("Minimize this window while recording / playing")
        self.minimize_cb.setChecked(bool(self.storage.get_setting("minimize_while_active", True)))
        self.minimize_cb.toggled.connect(lambda v: self.storage.set_setting("minimize_while_active", v))
        f.addRow("", self.minimize_cb)
        self.countdown = QSpinBox()
        self.countdown.setRange(0, 30)
        self.countdown.setSuffix(" s")
        self.countdown.setValue(int(self.storage.get_setting("countdown_seconds")))
        self.countdown.valueChanged.connect(lambda v: self.storage.set_setting("countdown_seconds", v))
        self.countdown.setToolTip("Time to click into your game before recording/playback starts")
        f.addRow("Countdown before start:", self.countdown)
        rl.addLayout(f)
        rl.addStretch(1)
        grid.addWidget(rc, 0, 0)

        # ---- playback card
        pc, pl = card("Playback", "These settings are saved with the macro.")
        self.r_once = QRadioButton("Play once")
        self.r_count = QRadioButton("Repeat")
        self.r_forever = QRadioButton("Repeat until stopped")
        g = QButtonGroup(self)
        for b in (self.r_once, self.r_count, self.r_forever):
            g.addButton(b)
        self.repeat_n = QSpinBox()
        self.repeat_n.setRange(1, 1000000)
        self.repeat_n.setSuffix(" times")
        pl.addWidget(self.r_once)
        pl.addLayout(row(self.r_count, self.repeat_n, None))
        pl.addWidget(self.r_forever)
        pf = QFormLayout()
        self.loop_delay = QDoubleSpinBox()
        self.loop_delay.setRange(0, 24 * 3600)
        self.loop_delay.setDecimals(2)
        self.loop_delay.setSuffix(" s")
        pf.addRow("Pause between loops:", self.loop_delay)
        self.speed = QComboBox()
        self.speed.setEditable(True)
        for s in ("0.25", "0.5", "0.75", "1", "1.5", "2", "3", "4"):
            self.speed.addItem(f"{s}x", float(s))
        pf.addRow("Speed:", self.speed)
        pl.addLayout(pf)
        for w in (self.r_once, self.r_count, self.r_forever):
            w.toggled.connect(self._playback_changed)
        self.repeat_n.valueChanged.connect(self._playback_changed)
        self.loop_delay.valueChanged.connect(self._playback_changed)
        self.speed.currentTextChanged.connect(self._playback_changed)
        self.play_b = button("▶ Play", self.play, kind="primary")
        self.stopplay_b = button("■ Stop playback", self.stop_play)
        pl.addLayout(row(self.play_b, self.stopplay_b, None))
        self.progress = QProgressBar()
        self.progress.setFormat("Idle")
        self.progress.setValue(0)
        pl.addWidget(self.progress)
        pl.addStretch(1)
        grid.addWidget(pc, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(1000)
        self._cd_timer.timeout.connect(self._countdown_tick)

        engine.state_changed.connect(self._update_state)
        engine.recording_event.connect(lambda n: self.count.setText(f"{n} steps recorded"))
        engine.playback_progress.connect(self._progress)
        session.loaded.connect(self._load_macro)
        session.playback_changed.connect(lambda src: src is not self and self._load_playback())
        session.list_changed.connect(self._reload_list)
        session.changed.connect(lambda rows: self._update_info())
        session.saved.connect(self._update_info)
        self._reload_list()
        self._load_macro()
        self.update_hints()

    # ---- macro list ---------------------------------------------------
    def _reload_list(self):
        self.macro_cb.blockSignals(True)
        self.macro_cb.clear()
        cur = self.session.macro
        found = False
        for m in self.storage.list_macros():
            self.macro_cb.addItem(f"{m['name']}  ({m['steps']} steps, {format_clock(m['duration'])})", m["id"])
            if m["id"] == cur.id:
                found = True
                self.macro_cb.setCurrentIndex(self.macro_cb.count() - 1)
        if not found:
            self.macro_cb.insertItem(0, f"{cur.name}  (not saved yet)", None)
            self.macro_cb.setCurrentIndex(0)
        self.macro_cb.blockSignals(False)

    def _load_macro(self):
        self._load_playback()
        self._reload_list()
        self._update_info()

    def _load_playback(self):
        pb = self.session.macro.playback
        for w in (self.r_once, self.r_count, self.r_forever, self.repeat_n, self.loop_delay, self.speed):
            w.blockSignals(True)
        {"once": self.r_once, "count": self.r_count, "forever": self.r_forever}[pb.repeat_mode].setChecked(True)
        self.repeat_n.setValue(pb.repeat_count)
        self.loop_delay.setValue(pb.loop_delay)
        self.speed.setCurrentText(f"{pb.speed:g}x")
        for w in (self.r_once, self.r_count, self.r_forever, self.repeat_n, self.loop_delay, self.speed):
            w.blockSignals(False)
        self._update_info()

    def _update_info(self):
        m = self.session.macro
        self.macro_info.setText(f"{len(m.actions)} steps, length {format_clock(m.total_duration())}"
                                + ("  •  unsaved changes — click Save" if self.session.dirty else "  •  saved"))
        if not self.engine.recording and not self.engine.player.playing:
            self.clock.setText(format_clock(m.total_duration()))
            self.count.setText(f"{len(m.actions)} steps")

    def _check_unsaved(self) -> bool:
        if not self.session.dirty or not self.session.macro.actions:
            return True
        box = confirm(self, "Unsaved changes", f"Save changes to '{self.session.macro.name}' first?",
                      yes="Save", no="Don't save")
        if box:
            return self._save()
        return True

    def _pick_macro(self, idx):
        mid = self.macro_cb.itemData(idx)
        if mid is None or mid == self.session.macro.id:
            return
        if not self._check_unsaved():
            self._reload_list()
            return
        self.session.open(mid)

    def _new(self):
        if not self._check_unsaved():
            return
        name, ok = QInputDialog.getText(self, "New macro", "Name:", text=self.storage.unique_macro_name("New macro"))
        if ok:
            self.session.new(name.strip() or None)

    def _rename(self):
        name, ok = QInputDialog.getText(self, "Rename macro", "New name:", text=self.session.macro.name)
        if ok:
            try:
                self.session.rename(name)
            except ValueError as e:
                error_box(self, "Rename", e)

    def _delete(self):
        m = self.session.macro
        if confirm(self, "Delete macro", f"Delete '{m.name}'? Scheduled runs of it are removed too.", yes="Delete"):
            self.session.delete_current()

    def _save(self) -> bool:
        try:
            self.session.save()
            return True
        except ValueError as e:
            error_box(self, "Could not save", e)
            return False

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import macro", "", "Macro files (*.json)")
        if not path:
            return
        if not self._check_unsaved():
            return
        try:
            m = self.session.import_json(path)
        except Exception as e:
            return error_box(self, "Import failed", e)
        msg = f"Imported '{m.name}' with {len(m.actions)} steps."
        if getattr(m, "missing_channels", 0):
            msg += (f"\n\n{m.missing_channels} Discord step(s) point to a channel that is not set up on this "
                    "computer. Edit those steps in the Timeline Editor to pick a channel.")
        info_box(self, "Imported", msg)

    def _export(self):
        safe = "".join(c for c in self.session.macro.name if c.isalnum() or c in " -_").strip() or "macro"
        path, _ = QFileDialog.getSaveFileName(self, "Export macro", f"{safe}.json", "Macro files (*.json)")
        if path:
            try:
                self.session.export_json(path)
                info_box(self, "Exported", f"Saved to {path}\n\n(Discord passwords/webhook links are never included.)")
            except Exception as e:
                error_box(self, "Export failed", e)

    # ---- playback settings --------------------------------------------
    def _playback_settings(self) -> PlaybackSettings:
        mode = "count" if self.r_count.isChecked() else "forever" if self.r_forever.isChecked() else "once"
        txt = self.speed.currentText().lower().replace("x", "").strip()
        try:
            speed = float(txt)
        except ValueError:
            speed = 1.0
        return PlaybackSettings.from_dict({"repeat_mode": mode, "repeat_count": self.repeat_n.value(),
                                           "loop_delay": self.loop_delay.value(), "speed": speed})

    def _playback_changed(self, *a):
        self.session.macro.playback = self._playback_settings()
        self.session.timeline.dirty = True
        self._update_info()
        self.session.playback_changed.emit(self)

    # ---- recording ----------------------------------------------------
    def update_hints(self):
        s = self.storage
        self.hint.setText(
            f"Hotkeys work from inside your game:  {keynames.hotkey_label(s.get_setting('hotkey_record'))} = "
            f"start/stop recording,  {keynames.hotkey_label(s.get_setting('hotkey_pause'))} = pause/resume,  "
            f"{keynames.hotkey_label(s.get_setting('hotkey_play'))} = play/stop,  "
            f"{keynames.hotkey_label(s.get_setting('hotkey_stop'))} = EMERGENCY STOP. "
            "Hotkey keys themselves are never recorded.")

    def start_record(self, insert_at=None):
        if self.engine.recording or self._countdown_left:
            return
        if self.engine.player.playing:
            return error_box(self, "Busy", "Stop playback before recording.")
        mode = self.mode_cb.currentData()
        if insert_at is not None:
            mode = "insert"
        if mode == "replace" and self.session.macro.actions:
            if not confirm(self, "Replace steps?", f"This replaces the {len(self.session.macro.actions)} existing "
                           "steps (you can Undo in the Timeline Editor).", yes="Record"):
                return
        if mode == "insert":
            pos = insert_at if insert_at is not None else self.session.insert_row
            self._pending_insert_at = len(self.session.macro.actions) if pos is None else pos
        else:
            self._pending_insert_at = None
        self._mode = mode
        self._begin_countdown(self._really_start_record, "Recording")

    def _begin_countdown(self, action, label):
        secs = self.countdown.value()
        if self.minimize_cb.isChecked():
            self.request_minimize.emit()
        if secs <= 0:
            action()
            return
        self._countdown_left = secs
        self._countdown_action = action
        self._countdown_label = label
        self.status.setText(f"{label} starts in {secs}…")
        self.engine.log.info("Recording" if label == "Recording" else "Playback", f"{label} starts in {secs} s.")
        self._cd_timer.start()
        self._update_state()

    def _countdown_tick(self):
        self._countdown_left -= 1
        if self._countdown_left > 0:
            self.status.setText(f"{self._countdown_label} starts in {self._countdown_left}…")
            return
        self._cd_timer.stop()
        act, self._countdown_action = self._countdown_action, None
        if act:
            act()

    def cancel_countdown(self):
        if self._countdown_left:
            self._cd_timer.stop()
            self._countdown_left = 0
            self._countdown_action = None
            self.status.setText("Cancelled")
            self._update_state()

    def _really_start_record(self):
        try:
            self.engine.start_recording()
        except Exception as e:
            self.request_restore.emit()
            return error_box(self, "Could not record", e)
        self.timer.start()
        self._update_state()

    def pause_record(self):
        if self.engine.recording and not self.engine.recorder.paused:
            self.engine.recorder.pause()
            self.engine.log.info("Recording", "Recording paused.")
            self._update_state()

    def resume_record(self):
        if self.engine.recording and self.engine.recorder.paused:
            self.engine.recorder.resume()
            self.engine.log.info("Recording", "Recording resumed.")
            self._update_state()

    def toggle_pause(self):
        if self.engine.recording:
            (self.resume_record if self.engine.recorder.paused else self.pause_record)()

    def stop_record(self, source="button"):
        if self._countdown_left:
            return self.cancel_countdown()
        if not self.engine.recording and not self.engine.player.playing:
            return
        trim = {"button": 1, "tray": 2}.get(source, 0)
        acts = self.engine.stop_recording(trim_clicks=trim)
        self.timer.stop()
        tl = self.session.timeline
        if not acts:
            self.status.setText("Nothing was recorded")
        elif self._mode == "replace":
            rows = tl.replace_all(acts)
            self.session.emit_changed(rows[:1])
        elif self._mode == "append":
            rows = tl.insert(len(tl), acts, label="Record")
            self.session.emit_changed(rows)
        else:
            rows = tl.insert(self._pending_insert_at or 0, acts, label="Record")
            self.session.emit_changed(rows)
        self._update_state()
        self.request_restore.emit()
        if acts:
            self.status.setText(f"Recorded {len(acts)} steps — not saved yet")
            self.show_timeline.emit()

    def toggle_record(self):
        if self.engine.recording or self._countdown_left:
            self.stop_record("hotkey")
        else:
            self.start_record()

    def _tick(self):
        if self.engine.player.playing:
            self.clock.setText(format_clock(self.engine.player.elapsed()))
            return
        rec = self.engine.recorder
        if rec and rec.recording:
            self.clock.setText(format_clock(rec.elapsed()))

    # ---- playback -----------------------------------------------------
    def play(self):
        m = self.session.macro
        if not m.actions:
            return error_box(self, "Nothing to play", "Record or add some steps first.")
        if self.engine.player.playing or self._countdown_left:
            return
        m.playback = self._playback_settings()
        self._begin_countdown(lambda: self._really_play(m), "Playback")

    def play_macro(self, macro):
        if self.engine.player.playing or self.engine.recording:
            return
        self._begin_countdown(lambda: self._really_play(macro), "Playback")

    def _really_play(self, macro):
        try:
            self.engine.play(macro, macro.playback)
        except Exception as e:
            self.request_restore.emit()
            error_box(self, "Could not play", e)
        self._update_state()

    def stop_play(self):
        if self._countdown_left:
            return self.cancel_countdown()
        self.engine.player.stop(wait=0)
        self.engine.log.info("Playback", "Playback stopped by user.")

    def toggle_play(self):
        if self.engine.player.playing or self._countdown_left:
            self.stop_play()
        else:
            self.play()

    def _progress(self, loop, step, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(step + 1)
        self.progress.setFormat(f"Loop {loop}  •  step {step + 1} / {total}")

    # ---- state --------------------------------------------------------
    def _update_state(self):
        rec = self.engine.recording
        paused = rec and self.engine.recorder.paused
        playing = self.engine.player.playing
        counting = bool(self._countdown_left)
        if rec or playing:
            self.timer.start()
        else:
            self.timer.stop()
        self.rec_b.setEnabled(not rec and not playing and not counting)
        self.pause_b.setEnabled(rec and not paused)
        self.resume_b.setEnabled(bool(paused))
        self.stop_b.setEnabled(rec or (counting and self._countdown_label == "Recording"))
        self.play_b.setEnabled(not rec and not playing and not counting)
        self.stopplay_b.setEnabled(playing or (counting and self._countdown_label == "Playback"))
        self.mode_cb.setEnabled(not rec)
        if rec:
            self.status.setText("● PAUSED" if paused else "● RECORDING")
        elif playing:
            self.status.setText(f"▶ Playing '{self.engine.now_playing}'")
        elif not counting and self.status.text().startswith(("●", "▶")):
            self.status.setText("Ready")
        if not playing and not counting:
            if self.progress.format() != "Idle" and self.progress.value() < self.progress.maximum():
                self.progress.setFormat(self.progress.format() + "  (stopped)")
