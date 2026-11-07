"""Dashboard, Activity Logs and Settings pages."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QHeaderView, QLabel, QLineEdit, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea)

from ..core import keynames
from ..core import schedule as sm
from ..core.logbus import CATEGORIES
from ..core.models import format_clock
from ..core.storage import data_dir, parse_dt
from .common import KeyCaptureDialog, button, card, confirm, error_box, info_box, muted, page_layout, row
from .page_scheduler import relative


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


class LogsPage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        lay = page_layout(self, "Activity Logs", "Everything the app did: recording, playback, Discord messages and errors.")
        self.cat = QComboBox()
        self.cat.addItems(["All", "Errors"] + CATEGORIES)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.cat.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        lay.addLayout(row(QLabel("Show:"), self.cat, self.search, button("Export…", self._export),
                          button("Clear", self._clear)))
        self.table = _table(["Time", "Type", "Level", "Message"])
        self.table.setWordWrap(True)
        lay.addWidget(self.table, 1)
        engine.log_entry.connect(lambda e: self.isVisible() and self.refresh())

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        logs = self.storage.list_logs(limit=1000, category=self.cat.currentText(), search=self.search.text().strip())
        self.table.setRowCount(len(logs))
        for r, l in enumerate(logs):
            ts = parse_dt(l["ts"]).strftime("%Y-%m-%d %H:%M:%S")
            for c, v in enumerate([ts, l["category"], l["level"], l["message"]]):
                it = QTableWidgetItem(v)
                if l["level"] == "error":
                    it.setForeground(Qt.red)
                elif l["level"] == "warning":
                    it.setForeground(Qt.darkYellow)
                self.table.setItem(r, c, it)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export log", "novamacrohub-log.txt", "Text files (*.txt)")
        if not path:
            return
        logs = self.storage.list_logs(limit=100000)
        with open(path, "w", encoding="utf-8") as f:
            for l in reversed(logs):
                f.write(f"{l['ts']}  [{l['category']}] {l['level'].upper()}: {l['message']}\n")
        info_box(self, "Exported", f"Saved {len(logs)} lines to {path}")

    def _clear(self):
        if confirm(self, "Clear log", "Delete all activity history?", yes="Clear"):
            self.storage.clear_logs()
            self.refresh()


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    appearance_changed = Signal()
    hotkeys_changed = Signal()

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        outer = page_layout(self, "Settings")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        s = self.storage

        # appearance
        c, l = card("Appearance")
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.get_setting("theme"))))
        self.theme.currentIndexChanged.connect(self._theme)
        f = QFormLayout()
        f.addRow("Theme", self.theme)
        self.bg_label = muted("", wrap=False)
        self.mascot_label = muted("", wrap=False)
        f.addRow("Background picture", row(button("Choose…", lambda: self._pick_image("background_image")),
                                           button("Use blossoms", lambda: self._clear_image("background_image")),
                                           self.bg_label, None))
        f.addRow("Mascot picture", row(button("Choose…", lambda: self._pick_image("mascot_image")),
                                       button("Use cat", lambda: self._clear_image("mascot_image")),
                                       self.mascot_label, None))
        l.addLayout(f)
        l.addWidget(muted("Use any picture of your own (PNG with a transparent background looks best for the mascot)."))
        self._show_images()
        lay.addWidget(c)

        # hotkeys
        c, l = card("Global hotkeys", "These work even while your game is in front. The emergency stop always works, "
                                      "even if a macro is holding other keys down.")
        f = QFormLayout()
        self.hk_buttons = {}
        for key, label in [("hotkey_stop", "EMERGENCY STOP (all playback)"), ("hotkey_record", "Start / stop recording"),
                           ("hotkey_pause", "Pause / resume recording"), ("hotkey_play", "Play / stop current macro")]:
            b = button(keynames.hotkey_label(s.get_setting(key)), lambda _=False, k=key: self._set_hotkey(k))
            b.setMinimumWidth(180)
            self.hk_buttons[key] = b
            f.addRow(label, b)
        l.addLayout(f)
        l.addWidget(muted("Click a button, then press the new key or combination."))
        lay.addWidget(c)

        # recording & playback
        c, l = card("Recording & playback")
        f = QFormLayout()
        self.moves = QCheckBox("Record mouse movement")
        self.moves.setChecked(bool(s.get_setting("record_mouse_moves")))
        self.moves.toggled.connect(lambda v: s.set_setting("record_mouse_moves", v))
        f.addRow("", self.moves)
        self.move_ms = QSpinBox()
        self.move_ms.setRange(1, 1000)
        self.move_ms.setSuffix(" ms")
        self.move_ms.setValue(int(s.get_setting("mouse_move_interval_ms")))
        self.move_ms.valueChanged.connect(lambda v: s.set_setting("mouse_move_interval_ms", v))
        f.addRow("Record mouse position at most every", self.move_ms)
        self.input_mode = QComboBox()
        self.input_mode.addItem("Game mode — hardware scan codes (recommended for games)", "scancode")
        self.input_mode.addItem("Standard — virtual keys (some desktop apps prefer this)", "virtualkey")
        self.input_mode.setCurrentIndex(max(0, self.input_mode.findData(s.get_setting("input_mode"))))
        self.input_mode.currentIndexChanged.connect(lambda _: s.set_setting("input_mode", self.input_mode.currentData()))
        f.addRow("Key sending", self.input_mode)
        l.addLayout(f)
        lay.addWidget(c)

        # discord safety
        c, l = card("Discord safety")
        f = QFormLayout()
        self.flood = QSpinBox()
        self.flood.setRange(1, 60)
        self.flood.setValue(int(s.get_setting("flood_per_minute")))
        self.flood.valueChanged.connect(lambda v: s.set_setting("flood_per_minute", v))
        f.addRow("Max messages per channel per minute", self.flood)
        self.min_int = QSpinBox()
        self.min_int.setRange(5, 3600)
        self.min_int.setSuffix(" s")
        self.min_int.setValue(int(s.get_setting("min_interval_seconds")))
        self.min_int.valueChanged.connect(lambda v: s.set_setting("min_interval_seconds", v))
        f.addRow("Shortest repeat interval allowed", self.min_int)
        self.catchup = QSpinBox()
        self.catchup.setRange(1, 240)
        self.catchup.setSuffix(" min")
        self.catchup.setValue(int(s.get_setting("catchup_minutes")))
        self.catchup.valueChanged.connect(lambda v: s.set_setting("catchup_minutes", v))
        f.addRow("Send late messages if less than", self.catchup)
        l.addLayout(f)
        l.addWidget(muted("If the PC was asleep or the app was closed at send time, messages later than this are "
                          "skipped (and logged) instead of being sent late in a burst."))
        lay.addWidget(c)

        # startup
        c, l = card("Startup & tray")
        self.tray = QCheckBox("Closing the window keeps the app running in the system tray")
        self.tray.setChecked(bool(s.get_setting("minimize_to_tray")))
        self.tray.toggled.connect(lambda v: s.set_setting("minimize_to_tray", v))
        self.start_min = QCheckBox("Start minimized to the tray")
        self.start_min.setChecked(bool(s.get_setting("start_minimized")))
        self.start_min.toggled.connect(lambda v: s.set_setting("start_minimized", v))
        self.autostart = QCheckBox("Start with Windows (so scheduled messages keep working after a reboot)")
        self.autostart.setChecked(bool(s.get_setting("start_with_windows")))
        self.autostart.toggled.connect(self._autostart)
        for w in (self.tray, self.start_min, self.autostart):
            l.addWidget(w)
        lay.addWidget(c)

        # data
        c, l = card("Data", f"Everything is stored on this PC in: {data_dir()}")
        l.addLayout(row(button("Open data folder", self._open_data), None))
        l.addWidget(muted(f"Bot token and webhook links are stored in {engine.secrets.backend_name}, "
                          "never in the database or in exported files."))
        lay.addWidget(c)
        lay.addStretch(1)

    def _theme(self):
        v = self.theme.currentData()
        self.storage.set_setting("theme", v)
        self.theme_changed.emit(v)

    def _show_images(self):
        import os.path
        for key, lbl in (("background_image", self.bg_label), ("mascot_image", self.mascot_label)):
            pth = self.storage.get_setting(key, None)
            lbl.setText(os.path.basename(pth) if pth else "default")

    def _pick_image(self, key):
        path, _ = QFileDialog.getOpenFileName(self, "Choose picture", "", "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        # copy into the data folder so it still works if the original is moved
        import shutil
        from pathlib import Path
        dest = data_dir() / f"{key}{Path(path).suffix.lower()}"
        try:
            shutil.copyfile(path, dest)
        except Exception as e:
            return error_box(self, "Picture", e)
        self.storage.set_setting(key, str(dest))
        self._show_images()
        self.appearance_changed.emit()

    def _clear_image(self, key):
        self.storage.set_setting(key, None)
        self._show_images()
        self.appearance_changed.emit()

    def _set_hotkey(self, key):
        d = KeyCaptureDialog(self, hotkey_mode=True, title="Set hotkey")
        if not d.exec() or not d.result_text:
            return
        old = self.storage.get_setting(key)
        self.storage.set_setting(key, d.result_text)
        errors = self.engine.apply_hotkeys()
        if errors:
            self.storage.set_setting(key, old)
            self.engine.apply_hotkeys()
            return error_box(self, "Hotkey not set", "\n".join(errors))
        self.hk_buttons[key].setText(keynames.hotkey_label(d.result_text))
        self.engine.log.info("System", f"Hotkey changed: {key.replace('hotkey_', '')} = {keynames.hotkey_label(d.result_text)}")
        self.hotkeys_changed.emit()

    def _autostart(self, v):
        try:
            self.engine.set_autostart(v)
            self.storage.set_setting("start_with_windows", v)
        except Exception as e:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not v)
            self.autostart.blockSignals(False)
            error_box(self, "Start with Windows", e)

    def _open_data(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))
