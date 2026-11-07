"""Dashboard: the all-in-one workspace (status, quick actions, recorder, timeline,
action editor, playback options, Discord and scheduler at a glance)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
                               QAbstractItemView)

from ..core import keynames
from ..core import schedule as sm
from ..core.models import ACTION_TYPES, format_clock
from ..core.storage import parse_dt
from .action_dialog import ActionEditor
from .common import (ToggleSwitch, button, card, error_box, info_box, muted, paint_cat, row, run_async)
from .page_scheduler import relative
from .page_timeline import StepView


class Mascot(QWidget):
    """The cat mascot, or the user's own picture (Settings → Appearance)."""

    def __init__(self, storage):
        super().__init__()
        self.storage = storage
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._pix = None
        self.reload()

    def reload(self):
        path = self.storage.get_setting("mascot_image", None)
        pm = QPixmap(path) if path else None
        if pm is None or pm.isNull():
            pm = QPixmap(str(Path(__file__).resolve().parents[2] / "assets" / "nova-heart-mascot.png"))
        self._pix = pm if pm is not None and not pm.isNull() else None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._pix:
            pm = self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.width() - pm.width()) // 2, self.height() - pm.height(), pm)
        else:
            s = min(self.height() - 10, self.width() * 0.5)
            paint_cat(p, 6, self.height() - s - 4, s)
        p.end()


def tile_button(text, kind, slot):
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setMinimumHeight(58)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class StatusTile(QFrame):
    def __init__(self, icon, title, btn_text, slot, color):
        super().__init__()
        self.setObjectName("tile")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 5, 10, 5)
        ic = QLabel(icon)
        ic.setStyleSheet(f"font-size: 20pt; color: {color};")
        ic.setFixedWidth(40)
        h.addWidget(ic)
        v = QVBoxLayout()
        v.setSpacing(0)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        self.state = QLabel("")
        self.state.setObjectName("tilestate")
        v.addWidget(t)
        v.addWidget(self.state)
        h.addLayout(v, 1)
        self.btn = button(btn_text, slot)
        self.btn.setMinimumWidth(74)
        h.addWidget(self.btn)

    def set_state(self, text, color, tile_state=""):
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.setProperty("state", tile_state)
        self.style().unpolish(self)
        self.style().polish(self)


class DashboardPage(QWidget):
    goto = Signal(str)

    def __init__(self, engine, session, pages):
        super().__init__()
        self.engine = engine
        self.session = session
        self.storage = engine.storage
        self.pages = pages          # dict of the other pages, to reuse their actions
        self.rec = pages["recorder"]
        self.tlp = pages["timeline"]
        self._editing_row = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        main = QHBoxLayout(content)
        main.setContentsMargins(0, 0, 4, 0)
        main.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(12)
        main.addLayout(left, 0)
        rightarea = QVBoxLayout()
        rightarea.setSpacing(12)
        main.addLayout(rightarea, 1)
        top = QHBoxLayout()
        top.setSpacing(12)
        rightarea.addLayout(top, 1)
        center = QVBoxLayout()
        center.setSpacing(12)
        top.addLayout(center, 1)
        right = QVBoxLayout()
        right.setSpacing(12)
        top.addLayout(right, 0)
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        rightarea.addLayout(bottom, 0)

        left_w = 320
        right_w = 290

        # ---------------------------------------------------- status overview
        c, l = card("Status Overview", icon="📊")
        c.setFixedWidth(left_w)
        self.t_play = StatusTile("▶", "Macro Playback", "Play", self.rec.toggle_play, "#2bd47a")
        self.t_rec = StatusTile("⏺", "Recording", "Record", self._toggle_record, "#ff3d6e")
        self.t_sched = StatusTile("📅", "Scheduled Messages", "View", lambda: self.goto.emit("scheduler"), "#4f86ff")
        self.t_rec.btn.setProperty("kind", "danger")
        for t in (self.t_play, self.t_rec, self.t_sched):
            l.addWidget(t)
        left.addWidget(c)

        # ---------------------------------------------------- upcoming
        c, l = card("Upcoming Messages", icon="💬")
        c.setFixedWidth(left_w)
        va = QPushButton("View All")
        va.setFlat(True)
        va.setStyleSheet("border: none; background: transparent; text-decoration: underline;")
        va.setCursor(Qt.PointingHandCursor)
        va.clicked.connect(lambda: self.goto.emit("scheduler"))
        c.header.addWidget(va)
        self.upcoming_box = QVBoxLayout()
        self.upcoming_box.setSpacing(6)
        l.addLayout(self.upcoming_box)
        left.addWidget(c)

        # ---------------------------------------------------- quick actions
        c, l = card("Quick Actions", icon="⚡")
        c.setFixedWidth(left_w)
        g = QGridLayout()
        g.setSpacing(8)
        g.addWidget(tile_button("⏺\nRecord Macro", "qa_rec", self._toggle_record), 0, 0)
        g.addWidget(tile_button("▶\nPlay Macro", "qa_play", self.rec.play), 0, 1)
        g.addWidget(tile_button("■\nStop All", "qa_stop", self._stop_all), 0, 2)
        g.addWidget(tile_button("📅\nNew Schedule", "qa_blue", lambda: self.pages["scheduler"]._new("message")), 1, 0)
        g.addWidget(tile_button("💬\nTest Discord", "qa_violet", self._test_discord), 1, 1)
        g.addWidget(tile_button("📜\nOpen Logs", "qa_indigo", lambda: self.goto.emit("logs")), 1, 2)
        l.addLayout(g)
        left.addWidget(c)

        # ---------------------------------------------------- system tray + mascot
        c, l = card("System Tray", icon="🐾")
        c.setFixedWidth(left_w)
        h = QHBoxLayout()
        h.setSpacing(4)
        self.mascot = Mascot(self.storage)
        h.addWidget(self.mascot, 1)
        v = QVBoxLayout()
        self.cb_tray = QCheckBox("Minimize to tray")
        self.cb_tray.setChecked(bool(self.storage.get_setting("minimize_to_tray")))
        self.cb_tray.toggled.connect(lambda v: self.storage.set_setting("minimize_to_tray", v))
        self.cb_auto = QCheckBox("Start with Windows")
        self.cb_auto.setChecked(bool(self.storage.get_setting("start_with_windows")))
        self.cb_auto.toggled.connect(self._autostart)
        v.addWidget(self.cb_tray)
        v.addWidget(self.cb_auto)
        tag = QLabel("Automate\nYour Adventure\nTogether! ♡")
        tag.setStyleSheet("font-size: 13pt; color: #ff9cdb;")
        tag.setObjectName("script")
        tag.setAlignment(Qt.AlignRight)
        v.addStretch(1)
        v.addWidget(tag)
        h.addLayout(v)
        l.addLayout(h, 1)
        c.setMinimumHeight(190)
        left.addWidget(c, 1)

        # ---------------------------------------------------- recorder
        c, l = card("Macro Recorder", icon="🎬")
        c.header.addWidget(QLabel("Profile:"))
        self.profile = QComboBox()
        self.profile.setMinimumWidth(190)
        self.profile.activated.connect(self._pick_profile)
        c.header.addWidget(self.profile)
        for txt, tip, slot in (("＋", "New macro", self.rec._new), ("📂", "Import JSON", self.rec._import),
                               ("💾", "Save", self.rec._save), ("⤓", "Export JSON", self.rec._export)):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            c.header.addWidget(b)
        self.b_rec = button("●  Record", self._toggle_record, kind="danger")
        self.b_pause = button("❚❚  Pause", self.rec.toggle_pause)
        self.b_stop = button("■  Stop", self._stop_any)
        self.b_play = button("▶  Play", self.rec.play, kind="violet")
        for b in (self.b_rec, self.b_pause, self.b_stop, self.b_play):
            b.setProperty("size", "big")
        rep = QVBoxLayout()
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 1000000)
        self.loop_cb = QCheckBox("Loop until stopped")
        rep.addLayout(row(QLabel("Repeat:"), self.repeat))
        rep.addWidget(self.loop_cb)
        self.rec_clock = QLabel("00:00.00")
        self.rec_clock.setObjectName("bigclock")
        self.rec_clock.setStyleSheet("font-size: 15pt;")
        l.addLayout(row(self.b_rec, self.b_pause, self.b_stop, self.b_play, None, self.rec_clock, rep))
        hk = QHBoxLayout()
        hk.setSpacing(8)
        hk.addWidget(muted("Global Hotkeys:", wrap=False))
        self.hk_labels = {}
        for key, label in (("hotkey_record", "Start/Stop Rec"), ("hotkey_pause", "Pause"),
                           ("hotkey_play", "Play Macro"), ("hotkey_stop", "Emergency Stop")):
            chip = QFrame()
            chip.setObjectName("chip")
            ch = QHBoxLayout(chip)
            ch.setContentsMargins(8, 3, 3, 3)
            ch.addWidget(QLabel(label))
            kb = QPushButton()
            kb.setObjectName("hk")
            kb.setToolTip("Click to change")
            kb.setCursor(Qt.PointingHandCursor)
            kb.clicked.connect(lambda _=False, k=key: self.pages["settings"]._set_hotkey(k))
            ch.addWidget(kb)
            self.hk_labels[key] = kb
            hk.addWidget(chip)
        hk.addStretch(1)
        l.addLayout(hk)
        center.addWidget(c)

        # ---------------------------------------------------- timeline
        c, l = card("Macro Timeline Editor", icon="☰")
        self.steps_label = muted("", wrap=False)
        c.header.addWidget(self.steps_label)
        tb = QHBoxLayout()
        tb.setSpacing(6)
        add = QToolButton()
        add.setText("＋ Add Action")
        add.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(add)
        for k, lbl in ACTION_TYPES.items():
            m.addAction(lbl, lambda k=k: self.tlp.add_step(k))
        add.setMenu(m)
        tb.addWidget(add)
        for txt, slot in (("⏱ Insert Delay", lambda: self.tlp.add_step("wait")),
                          ("▶ Record Here", self.tlp._record_here), ("🗑 Delete", self.tlp.delete),
                          ("⧉ Copy", self.tlp.copy), ("📋 Paste", self.tlp.paste)):
            b = QToolButton()
            b.setText(txt)
            b.clicked.connect(slot)
            tb.addWidget(b)
        tb.addStretch(1)
        self.u_b = QToolButton(); self.u_b.setText("↶"); self.u_b.setToolTip("Undo (Ctrl+Z)")
        self.r_b = QToolButton(); self.r_b.setText("↷"); self.r_b.setToolTip("Redo (Ctrl+Y)")
        self.u_b.clicked.connect(self.tlp.undo)
        self.r_b.clicked.connect(self.tlp.redo)
        tb.addWidget(self.u_b)
        tb.addWidget(self.r_b)
        l.addLayout(tb)
        self.view = StepView(self.tlp.model)
        self.view.setSelectionModel(self.tlp.view.selectionModel())  # shared selection with the Timeline tab
        self.view.setMinimumHeight(330)
        self.view.doubleClicked.connect(self.tlp._double_clicked)
        self.view.rows_dropped.connect(self.tlp._dropped)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(
            lambda pos: self.tlp._context_menu_at(self.view, pos))
        l.addWidget(self.view, 1)
        center.addWidget(c, 1)

        # ---------------------------------------------------- action editor
        c, l = card("Action Editor", icon="🛠")
        c.setFixedWidth(right_w)
        trash = QToolButton()
        trash.setText("🗑")
        trash.setToolTip("Delete this step")
        trash.clicked.connect(self.tlp.delete)
        c.header.addWidget(trash)
        self.editor_hint = muted("Select one step in the timeline to edit it here.")
        l.addWidget(self.editor_hint)
        self.editor = ActionEditor(self.storage, compact=True)
        ed_scroll = QScrollArea()
        ed_scroll.setWidgetResizable(True)
        ed_scroll.setFrameShape(QFrame.NoFrame)
        ed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed_scroll.setWidget(self.editor)
        ed_scroll.setMinimumHeight(250)
        l.addWidget(ed_scroll, 1)
        self.apply_b = button("Apply changes", self._apply_edit, kind="primary")
        self.revert_b = button("Revert", self._load_editor)
        l.addLayout(row(self.apply_b, self.revert_b, None))
        right.addWidget(c, 1)

        # ---------------------------------------------------- playback options
        c, l = card("Playback Options", icon="🎛")
        c.setFixedWidth(right_w)
        l.addWidget(QLabel("Playback Speed"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(25, 400)
        self.speed.setSingleStep(25)
        self.speed.setPageStep(25)
        self.speed_lbl = QLabel("1.0x")
        self.speed_lbl.setFixedWidth(42)
        l.addLayout(row(self.speed, self.speed_lbl))
        self.repeat2 = QSpinBox()
        self.repeat2.setRange(1, 1000000)
        l.addLayout(row(QLabel("Repeat Count"), self.repeat2, None))
        self.loop2 = QCheckBox("Loop until stopped")
        l.addWidget(self.loop2)
        self.gap_cb = QCheckBox("Delay between loops")
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 24 * 3600)
        self.gap.setDecimals(1)
        self.gap.setSuffix(" s")
        l.addLayout(row(self.gap_cb, self.gap, None))
        right.addWidget(c)
        for w, sig in ((self.repeat, "valueChanged"), (self.loop_cb, "toggled"), (self.speed, "valueChanged"),
                       (self.repeat2, "valueChanged"), (self.loop2, "toggled"), (self.gap_cb, "toggled"),
                       (self.gap, "valueChanged")):
            getattr(w, sig).connect(lambda *a, w=w: self._playback_edited(w))

        # ---------------------------------------------------- discord mini
        c, l = card("Discord Manager", icon="💬")
        tabs = QTabWidget()
        bot = QWidget(); bl = QVBoxLayout(bot); bl.setContentsMargins(0, 8, 0, 0)
        self.bot_state = QLabel()
        self.bot_state.setStyleSheet("font-weight: 700;")
        self.bot_name = muted("", wrap=False)
        sv = QVBoxLayout(); sv.setSpacing(0); sv.addWidget(self.bot_state); sv.addWidget(self.bot_name)
        self.test_b = button("Test Message", self._test_discord, kind="primary")
        self.disc_b = button("Disconnect", self._disconnect)
        bl.addLayout(row(sv, None, self.test_b, self.disc_b))
        self.default_target = QComboBox()
        self.default_target.activated.connect(
            lambda _: self.storage.set_setting("default_target_id", self.default_target.currentData()))
        bl.addLayout(row(QLabel("Default Channel"), self.default_target))
        tabs.addTab(bot, "Bot Connection")
        wh = QWidget(); wl = QVBoxLayout(wh); wl.setContentsMargins(0, 8, 0, 0)
        self.wh_label = muted("")
        wl.addWidget(self.wh_label)
        wl.addLayout(row(button("＋ Add webhook", lambda: self._discord("_add_webhook"), kind="primary"),
                         button("Manage…", lambda: self.goto.emit("discord")), None))
        tabs.addTab(wh, "Webhooks")
        dt = QWidget(); dl = QVBoxLayout(dt); dl.setContentsMargins(0, 8, 0, 0)
        dl.addWidget(muted("Find the channel that is open in your Discord app, or paste a channel link."))
        dl.addLayout(row(button("🔍 Detect open channel", lambda: self._discord("_detect"), kind="primary"),
                         button("Paste channel link…", lambda: self._discord("_add_channel")), None))
        tabs.addTab(dt, "Channel Detection")
        l.addWidget(tabs)
        bottom.addWidget(c, 1)

        # ---------------------------------------------------- scheduler mini
        c, l = card("Message Scheduler", icon="📅")
        nm = button("＋ New Message", lambda: self.pages["scheduler"]._new("message"), kind="primary")
        c.header.addWidget(nm)
        self.sched = QTableWidget(0, 6)
        self.sched.setHorizontalHeaderLabels(["Enabled", "Name", "Channel", "Message Preview", "Schedule", "Next Send"])
        self.sched.verticalHeader().setVisible(False)
        self.sched.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sched.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.sched.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.sched.setMinimumHeight(150)
        self.sched.cellDoubleClicked.connect(lambda r, col: self.goto.emit("scheduler"))
        l.addWidget(self.sched)
        bottom.addWidget(c, 2)

        # ---------------------------------------------------- wiring
        engine.state_changed.connect(self.refresh_state)
        engine.schedules_changed.connect(self.refresh_schedules)
        session.loaded.connect(self._session_loaded)
        session.list_changed.connect(self._reload_profiles)
        session.changed.connect(lambda rows: self._after_change())
        session.saved.connect(self._reload_profiles)
        session.playback_changed.connect(lambda src: src is not self and self._load_playback())
        self.tlp.view.selectionModel().selectionChanged.connect(lambda *a: self._load_editor())
        self.tlp.view.selectionModel().currentRowChanged.connect(lambda *a: self._load_editor())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self._session_loaded()
        self.refresh_all()

    # ---------------------------------------------------- refresh
    def refresh_all(self):
        self.refresh_state()
        self.refresh_schedules()
        self.refresh_discord()
        self.refresh_hotkeys()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_all()

    def _session_loaded(self):
        self._reload_profiles()
        self._load_playback()
        self._after_change()

    def _reload_profiles(self):
        self.profile.blockSignals(True)
        self.profile.clear()
        cur = self.session.macro
        found = False
        for m in self.storage.list_macros():
            self.profile.addItem(m["name"], m["id"])
            if m["id"] == cur.id:
                self.profile.setCurrentIndex(self.profile.count() - 1)
                found = True
        if not found:
            self.profile.insertItem(0, f"{cur.name} (unsaved)", None)
            self.profile.setCurrentIndex(0)
        self.profile.blockSignals(False)

    def _pick_profile(self, idx):
        mid = self.profile.itemData(idx)
        if mid is None or mid == self.session.macro.id:
            return
        if self.rec._check_unsaved():
            self.session.open(mid)
        else:
            self._reload_profiles()

    def _after_change(self):
        tl = self.session.timeline
        self.steps_label.setText(f"{len(tl)} steps • {format_clock(tl.total())}"
                                 + ("  • unsaved" if self.session.dirty else ""))
        self.u_b.setEnabled(tl.can_undo())
        self.r_b.setEnabled(tl.can_redo())
        self._load_editor()

    def refresh_hotkeys(self):
        for key, b in self.hk_labels.items():
            b.setText(keynames.hotkey_label(self.storage.get_setting(key)))

    def refresh_state(self):
        e = self.engine
        playing, recording = e.player.playing, e.recording
        if playing:
            self.t_play.set_state(f"Playing: {e.now_playing}", "#2bd47a", "ok")
            self.t_play.btn.setText("Stop")
        else:
            self.t_play.set_state("Idle", "#2bd47a", "ok")
            self.t_play.btn.setText("Play")
        if recording:
            self.t_rec.set_state("Paused" if e.recorder.paused else "Recording…", "#ff3d6e", "rec")
            self.t_rec.btn.setText("Stop")
        else:
            self.t_rec.set_state("Not Recording", "#ff6b8f", "rec")
            self.t_rec.btn.setText("Record")
        self.b_rec.setText("■  Stop Rec" if recording else "●  Record")
        self.b_rec.setEnabled(not playing)
        self.b_pause.setEnabled(recording)
        self.b_pause.setText("▶  Resume" if recording and e.recorder.paused else "❚❚  Pause")
        self.b_play.setEnabled(not playing and not recording)
        self.b_stop.setEnabled(playing or recording or bool(self.rec._countdown_left))

    def refresh_schedules(self):
        scheds = self.storage.list_schedules("message")
        targets = {t["id"]: t for t in self.storage.list_targets()}
        n_on = sum(1 for s in scheds if s["enabled"])
        self.t_sched.set_state(f"{n_on} Active" + (" (paused)" if self.engine.scheduler.messages_paused else ""),
                               "#6f9bff", "info")
        # upcoming list
        while self.upcoming_box.count():
            it = self.upcoming_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        order = sorted(scheds, key=lambda s: (not s["enabled"], s["next_run_at"] or "9999"))
        self._next = {}
        for s in order[:4]:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 2, 4, 2)
            ic = QLabel("💬")
            ic.setStyleSheet("font-size: 16pt; color: #9b8cff;")
            h.addWidget(ic)
            v = QVBoxLayout()
            v.setSpacing(0)
            nm = QLabel(s["name"])
            nm.setStyleSheet("font-weight: 600;")
            t = targets.get(s["target_id"])
            ch = muted(t["name"] if t else "no channel", wrap=False)
            v.addWidget(nm)
            v.addWidget(ch)
            h.addLayout(v, 1)
            when = muted("", wrap=False)
            nxt = parse_dt(s["next_run_at"]) if s["enabled"] else None
            self._next[id(when)] = (when, nxt)
            when.setText(_short_rel(nxt) if nxt else "off")
            h.addWidget(when)
            sw = ToggleSwitch(bool(s["enabled"]))
            sw.toggled.connect(lambda v, sid=s["id"]: self._toggle_sched(sid, v))
            h.addWidget(sw)
            self.upcoming_box.addWidget(w)
        if not scheds:
            self.upcoming_box.addWidget(muted("No announcements yet. Click 'New Schedule' below."))
        # scheduler mini table
        self.sched.setRowCount(len(scheds))
        self._sched_next = {}
        for r, s in enumerate(scheds):
            sw = ToggleSwitch(bool(s["enabled"]))
            sw.toggled.connect(lambda v, sid=s["id"]: self._toggle_sched(sid, v))
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 0, 8, 0)
            hl.addWidget(sw)
            self.sched.setCellWidget(r, 0, holder)
            t = targets.get(s["target_id"])
            msg = (s["message"] or "").replace("\n", " ")
            nxt = parse_dt(s["next_run_at"]) if s["enabled"] else None
            vals = [s["name"], t["name"] if t else "—", msg[:40] + ("…" if len(msg) > 40 else ""),
                    sm.describe(s["kind"], s["params"]), _short_rel(nxt) if nxt else "—"]
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(v)
                if c == 5:
                    it.setForeground(Qt.green if nxt else Qt.gray)
                self.sched.setItem(r, c, it)
            self._sched_next[r] = nxt

    def refresh_discord(self):
        tok = self.engine.bot_token()
        name = self.storage.get_setting("bot_name", None)
        targets = self.storage.list_targets()
        webhooks = [t for t in targets if t["kind"] == "webhook"]
        if tok:
            self.bot_state.setText("● Connected")
            self.bot_state.setStyleSheet("font-weight: 700; color: #2bd47a;")
            self.bot_name.setText(f"Bot: {name or 'saved'}")
        elif webhooks:
            self.bot_state.setText("● Webhooks ready")
            self.bot_state.setStyleSheet("font-weight: 700; color: #2bd47a;")
            self.bot_name.setText("No bot (not needed for webhooks)")
        else:
            self.bot_state.setText("● Not set up")
            self.bot_state.setStyleSheet("font-weight: 700; color: #ff6b8f;")
            self.bot_name.setText("Add a webhook or bot to start")
        self.disc_b.setEnabled(bool(tok))
        cur = self.storage.get_setting("default_target_id", None)
        self.default_target.clear()
        for t in targets:
            label = t["name"] + (f"  ({t['channel_id']})" if t["channel_id"] else "")
            self.default_target.addItem(label, t["id"])
        if not targets:
            self.default_target.addItem("No channels yet", None)
        i = self.default_target.findData(cur)
        if i >= 0:
            self.default_target.setCurrentIndex(i)
        self.wh_label.setText(f"{len(webhooks)} webhook channel(s): " + (", ".join(t["name"] for t in webhooks) or "none yet"))

    def _tick(self):
        if not self.isVisible():
            return
        rec = self.engine.recorder
        if rec and rec.recording:
            self.rec_clock.setText(format_clock(rec.elapsed()))
        elif self.engine.player.playing:
            self.rec_clock.setText(format_clock(self.engine.player.elapsed()))
        else:
            self.rec_clock.setText(format_clock(self.session.timeline.total()))
        for when, nxt in getattr(self, "_next", {}).values():
            if nxt:
                try:
                    when.setText(_short_rel(nxt))
                except RuntimeError:
                    pass
        for r, nxt in getattr(self, "_sched_next", {}).items():
            it = self.sched.item(r, 5)
            if it and nxt:
                it.setText(_short_rel(nxt))
        self.refresh_state()

    # ---------------------------------------------------- actions
    def _toggle_record(self):
        if self.engine.recording or self.rec._countdown_left:
            self.rec.stop_record("button")
        else:
            self.rec.start_record()

    def _stop_any(self):
        if self.engine.recording or (self.rec._countdown_left and self.rec._countdown_label == "Recording"):
            self.rec.stop_record("button")
        else:
            self.rec.stop_play()

    def _stop_all(self):
        self.rec.cancel_countdown()
        self.engine.emergency_stop(source="Stop All button")

    def _toggle_sched(self, sid, on):
        self.pages["scheduler"]._set_enabled(sid, on)
        QTimer.singleShot(0, self.refresh_schedules)

    def _discord(self, method):
        page = self.pages["discord"]
        getattr(page, method)()
        self.refresh_discord()

    def _disconnect(self):
        self.pages["discord"]._remove_token()
        self.refresh_discord()

    def _test_discord(self):
        tid = self.storage.get_setting("default_target_id", None)
        targets = self.storage.list_targets()
        if not targets:
            info_box(self, "Discord", "Add a channel first (Discord Manager → Webhook is easiest).")
            return self.goto.emit("discord")
        if tid not in {t["id"] for t in targets}:
            tid = targets[0]["id"]
        name = next(t["name"] for t in targets if t["id"] == tid)
        self.test_b.setEnabled(False)

        def done(res, err):
            self.test_b.setEnabled(True)
            self.refresh_discord()
            if err or not res.ok:
                return error_box(self, "Test failed", err or res.error)
            info_box(self, "Sent", f"Test message sent to {name}.")

        run_async(self.engine.test_target, tid, on_done=done)

    def _autostart(self, v):
        try:
            self.engine.set_autostart(v)
            self.storage.set_setting("start_with_windows", v)
        except Exception as e:
            self.cb_auto.blockSignals(True)
            self.cb_auto.setChecked(not v)
            self.cb_auto.blockSignals(False)
            error_box(self, "Start with Windows", e)

    # ---------------------------------------------------- playback options
    def _load_playback(self):
        pb = self.session.macro.playback
        ws = (self.repeat, self.loop_cb, self.speed, self.repeat2, self.loop2, self.gap_cb, self.gap)
        for w in ws:
            w.blockSignals(True)
        self.repeat.setValue(pb.repeat_count if pb.repeat_mode == "count" else 1)
        self.repeat2.setValue(self.repeat.value())
        self.loop_cb.setChecked(pb.repeat_mode == "forever")
        self.loop2.setChecked(pb.repeat_mode == "forever")
        self.speed.setValue(int(round(pb.speed * 100)))
        self.speed_lbl.setText(f"{pb.speed:.2g}x")
        self.gap_cb.setChecked(pb.loop_delay > 0)
        self.gap.setValue(pb.loop_delay)
        self.gap.setEnabled(pb.loop_delay > 0)
        for w in ws:
            w.blockSignals(False)

    def _playback_edited(self, src):
        pb = self.session.macro.playback
        if src in (self.repeat, self.repeat2):
            n = src.value()
            pb.repeat_count = n
            if pb.repeat_mode != "forever":
                pb.repeat_mode = "count" if n > 1 else "once"
        elif src in (self.loop_cb, self.loop2):
            if src.isChecked():
                pb.repeat_mode = "forever"
            else:
                pb.repeat_mode = "count" if pb.repeat_count > 1 else "once"
        elif src is self.speed:
            v = round(self.speed.value() / 25) * 25 / 100
            pb.speed = max(0.25, v)
        elif src in (self.gap_cb, self.gap):
            pb.loop_delay = self.gap.value() if self.gap_cb.isChecked() else 0.0
            if self.gap_cb.isChecked() and pb.loop_delay == 0:
                self.gap.blockSignals(True)
                self.gap.setValue(5.0)
                self.gap.blockSignals(False)
                pb.loop_delay = 5.0
        self.session.timeline.dirty = True
        self._load_playback()
        self.session.playback_changed.emit(self)
        self._after_change()

    # ---------------------------------------------------- action editor
    def _load_editor(self):
        rows = self.tlp.selected_rows()
        ok = len(rows) == 1
        self.editor.setEnabled(ok)
        self.apply_b.setEnabled(ok)
        self.revert_b.setEnabled(ok)
        if not ok:
            self._editing_row = None
            self.editor_hint.setText("Select one step in the timeline to edit it here."
                                     if not rows else f"{len(rows)} steps selected — use Set delay… in the Timeline tab.")
            return
        r = rows[0]
        self._editing_row = r
        self.editor_hint.setText(f"Step {r + 1}: {self.session.timeline.actions[r].title()}")
        self.editor.reload_targets()
        self.editor.load(self.session.timeline.actions[r])

    def _apply_edit(self):
        r = self._editing_row
        if r is None or r >= len(self.session.timeline):
            return
        try:
            a = self.editor.build()
        except ValueError as e:
            return error_box(self, "Check this step", e)
        self.session.timeline.replace(r, a)
        self.session.emit_changed([r])


def _short_rel(dt):
    if not dt:
        return "—"
    secs = (dt - datetime.now().astimezone()).total_seconds()
    if secs < 0:
        return "now"
    if secs < 60:
        return f"in {int(secs)} s"
    if secs < 3600:
        return f"in {int(secs // 60)} minutes"
    if secs < 6 * 3600:
        h, m = int(secs // 3600), int(secs % 3600 // 60)
        return f"in {h}h {m}m"
    return sm.fmt_dt(dt)
