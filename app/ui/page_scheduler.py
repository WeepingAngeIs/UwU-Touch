"""Message Scheduler: Discord announcements and timed macro runs."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime, Qt, QTime, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
                               QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit, QRadioButton, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from ..core import schedule as sm
from ..core.scheduler import iso
from ..core.storage import parse_dt
from .common import ToggleSwitch, button, confirm, error_box, info_box, muted, page_layout, row, run_async

STATUS_TEXT = {"sent": "✔ Sent", "ran": "✔ Ran", "waiting": "Waiting", "sending": "Sending…",
               "retrying": "↻ Retrying", "failed": "✖ Failed", "missed": "Missed (app closed)",
               "skipped": "Skipped", "finished": "Finished", "off": "Off", None: "—"}


def relative(dt):
    if not dt:
        return "—"
    now = datetime.now().astimezone()
    secs = (dt - now).total_seconds()
    if secs < 0:
        return sm.fmt_dt(dt)
    if secs < 60:
        rel = f"in {int(secs)}s"
    elif secs < 3600:
        rel = f"in {int(secs // 60)}m {int(secs % 60)}s"
    elif secs < 86400:
        rel = f"in {int(secs // 3600)}h {int(secs % 3600 // 60)}m"
    else:
        rel = f"in {int(secs // 86400)}d"
    return f"{sm.fmt_dt(dt)}  ({rel})"


def to_qdt(dt):
    return QDateTime.fromSecsSinceEpoch(int(dt.timestamp()))


def from_qdt(q: QDateTime):
    return datetime.fromtimestamp(q.toSecsSinceEpoch()).astimezone()


class ScheduleDialog(QDialog):
    def __init__(self, parent, engine, job="message", sched=None):
        super().__init__(parent)
        self.engine = engine
        self.storage = engine.storage
        self.job = job
        self.sched = sched or {}
        self.result_id = None
        self.setWindowTitle(("Edit " if sched else "New ") + ("announcement" if job == "message" else "macro schedule"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(self.sched.get("name", ""))
        self.name.setPlaceholderText("e.g. Guild Raid Reminder")
        f.addRow("Name", self.name)
        if job == "message":
            self.target = QComboBox()
            for t in self.storage.list_targets():
                self.target.addItem(f"{t['name']}  ({'Webhook' if t['kind'] == 'webhook' else 'Bot'})", t["id"])
            if self.target.count() == 0:
                self.target.addItem("No channels yet — add one in the Discord Manager tab", None)
            i = self.target.findData(self.sched.get("target_id"))
            if i >= 0:
                self.target.setCurrentIndex(i)
            f.addRow("Discord channel", self.target)
            self.msg = QPlainTextEdit(self.sched.get("message", ""))
            self.msg.setPlaceholderText("⚔️ RAID TIME GUYS! Everyone log in! We're starting soon! 🔥")
            self.msg.setFixedHeight(100)
            self.counter = muted("", wrap=False)
            self.msg.textChanged.connect(self._count)
            f.addRow("Message", self.msg)
            f.addRow("", self.counter)
            self.everyone = QCheckBox("Allow @everyone / @here to ping people")
            self.everyone.setChecked(bool(self.sched.get("allow_everyone")))
            f.addRow("", self.everyone)
            self._count()
        else:
            self.macro = QComboBox()
            for m in self.storage.list_macros():
                self.macro.addItem(m["name"], m["id"])
            if self.macro.count() == 0:
                self.macro.addItem("No saved macros yet", None)
            i = self.macro.findData(self.sched.get("macro_id"))
            if i >= 0:
                self.macro.setCurrentIndex(i)
            f.addRow("Macro", self.macro)
            f.addRow("", muted("The macro plays with its own repeat/speed settings (Macro Recorder tab). "
                               "Put your game window in front before the scheduled time."))
        lay.addLayout(f)

        # schedule type
        kind = self.sched.get("kind", "interval")
        params = self.sched.get("params") or {}
        self.r_interval = QRadioButton("Repeat every…")
        self.r_daily = QRadioButton("At set times of day")
        self.r_once = QRadioButton("One time")
        g = QButtonGroup(self)
        for b in (self.r_interval, self.r_daily, self.r_once):
            g.addButton(b)
            b.toggled.connect(self._kind_changed)
        lay.addLayout(row(QLabel("When:"), self.r_interval, self.r_daily, self.r_once, None))
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        # interval page
        w = QWidget(); fl = QFormLayout(w)
        self.preset = QComboBox()
        for label, secs in sm.PRESETS:
            self.preset.addItem(label, secs)
        self.preset.addItem("Custom…", None)
        self.custom_n = QSpinBox(); self.custom_n.setRange(1, 1000000)
        self.custom_unit = QComboBox()
        for u, mult in (("seconds", 1), ("minutes", 60), ("hours", 3600), ("days", 86400)):
            self.custom_unit.addItem(u, mult)
        self.custom_row = _h(self.custom_n, self.custom_unit)
        fl.addRow("Every", self.preset)
        fl.addRow("Custom", self.custom_row)
        secs = params.get("seconds", 7200)
        i = self.preset.findData(secs)
        if i >= 0:
            self.preset.setCurrentIndex(i)
        else:
            self.preset.setCurrentIndex(self.preset.count() - 1)
            for mult, idx in ((86400, 3), (3600, 2), (60, 1), (1, 0)):
                if secs % mult == 0:
                    self.custom_n.setValue(int(secs // mult))
                    self.custom_unit.setCurrentIndex(idx)
                    break
        self.preset.currentIndexChanged.connect(self._preview)
        self.preset.currentIndexChanged.connect(lambda _: self.custom_row.setEnabled(self.preset.currentData() is None))
        self.custom_row.setEnabled(self.preset.currentData() is None)
        self.custom_n.valueChanged.connect(self._preview)
        self.custom_unit.currentIndexChanged.connect(self._preview)
        fl.addRow("", muted("Counts from when you switch it on, or from the Start time below if you set one."))
        self.stack.addWidget(w)

        # daily page
        w = QWidget(); vl = QVBoxLayout(w); vl.setContentsMargins(0, 0, 0, 0)
        self.time_edit = QTimeEdit(QTime(18, 0))
        self.time_edit.setDisplayFormat("h:mm AP")
        self.times = QListWidget()
        self.times.setFixedHeight(90)
        for t in params.get("times", []) if kind == "daily" else []:
            self.times.addItem(t)
        add = button("Add time", self._add_time)
        rem = button("Remove selected", self._remove_time)
        vl.addLayout(row(self.time_edit, add, rem, None))
        vl.addWidget(self.times)
        self.days = []
        dl = QHBoxLayout()
        sel_days = set(params.get("weekdays") or range(7)) if kind == "daily" else set(range(7))
        for i, n in enumerate(sm.WEEKDAY_NAMES):
            cb = QCheckBox(n)
            cb.setChecked(i in sel_days)
            cb.toggled.connect(self._preview)
            self.days.append(cb)
            dl.addWidget(cb)
        dl.addStretch(1)
        vl.addLayout(dl)
        vl.addLayout(row(button("Every day", lambda: self._set_days(range(7))),
                         button("Weekdays", lambda: self._set_days(range(5))),
                         button("Weekends", lambda: self._set_days([5, 6])), None))
        self.stack.addWidget(w)

        # once page
        w = QWidget(); fl = QFormLayout(w)
        self.once_at = QDateTimeEdit()
        self.once_at.setCalendarPopup(True)
        self.once_at.setDisplayFormat("ddd d MMM yyyy  h:mm AP")
        at = parse_dt(params.get("at")) if kind == "once" else None
        self.once_at.setDateTime(to_qdt(at or (datetime.now().astimezone() + timedelta(hours=1)).replace(second=0)))
        self.once_at.dateTimeChanged.connect(self._preview)
        fl.addRow("Send at", self.once_at)
        self.stack.addWidget(w)

        # window
        gl = QGridLayout()
        self.use_start = QCheckBox("Start at")
        self.use_end = QCheckBox("Stop after")
        self.start_at = QDateTimeEdit(); self.end_at = QDateTimeEdit()
        for e in (self.start_at, self.end_at):
            e.setCalendarPopup(True)
            e.setDisplayFormat("ddd d MMM yyyy  h:mm AP")
            e.dateTimeChanged.connect(self._preview)
        now = datetime.now().astimezone().replace(second=0)
        s_at, e_at = parse_dt(self.sched.get("start_at")), parse_dt(self.sched.get("end_at"))
        self.use_start.setChecked(bool(s_at))
        self.use_end.setChecked(bool(e_at))
        self.start_at.setDateTime(to_qdt(s_at or now + timedelta(minutes=5)))
        self.end_at.setDateTime(to_qdt(e_at or now + timedelta(days=7)))
        for cb in (self.use_start, self.use_end):
            cb.toggled.connect(self._preview)
        gl.addWidget(self.use_start, 0, 0); gl.addWidget(self.start_at, 0, 1)
        gl.addWidget(self.use_end, 1, 0); gl.addWidget(self.end_at, 1, 1)
        gl.addWidget(muted("Leave both unticked to repeat until you switch it off."), 2, 0, 1, 2)
        lay.addLayout(gl)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setObjectName("muted")
        lay.addWidget(self.preview)

        self.enable_cb = QCheckBox("Switch on after saving")
        self.enable_cb.setChecked(bool(self.sched.get("enabled", True)) if sched else True)
        lay.addWidget(self.enable_cb)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        if job == "message":
            self.test_b = bb.addButton("Send test now", QDialogButtonBox.ActionRole)
            self.test_b.clicked.connect(self._test)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        {"interval": self.r_interval, "daily": self.r_daily, "once": self.r_once}[kind].setChecked(True)
        self._kind_changed()

    # ---- helpers ------------------------------------------------------
    def _count(self):
        n = len(self.msg.toPlainText())
        self.counter.setText(f"{n} / 2000 characters" + ("  ⚠ too long" if n > 2000 else ""))

    def _set_days(self, days):
        for i, cb in enumerate(self.days):
            cb.setChecked(i in set(days))

    def _add_time(self):
        t = self.time_edit.time().toString("HH:mm")
        existing = [self.times.item(i).text() for i in range(self.times.count())]
        if t not in existing:
            existing.append(t)
            existing.sort()
            self.times.clear()
            self.times.addItems(existing)
        self._preview()

    def _remove_time(self):
        for it in self.times.selectedItems():
            self.times.takeItem(self.times.row(it))
        self._preview()

    def _kind(self):
        return "interval" if self.r_interval.isChecked() else "daily" if self.r_daily.isChecked() else "once"

    def _kind_changed(self):
        self.stack.setCurrentIndex({"interval": 0, "daily": 1, "once": 2}[self._kind()])
        self.use_start.setEnabled(self._kind() != "once")
        self.use_end.setEnabled(self._kind() != "once")
        self._preview()

    def _collect(self):
        kind = self._kind()
        if kind == "interval":
            secs = self.preset.currentData()
            if secs is None:
                secs = self.custom_n.value() * self.custom_unit.currentData()
            minimum = int(self.storage.get_setting("min_interval_seconds") or 10)
            if secs < minimum:
                raise ValueError(f"The shortest allowed interval is {minimum} seconds (change it in Settings). "
                                 "Very short intervals can get your bot or webhook rate-limited by Discord.")
            params = {"seconds": int(secs)}
            old = self.sched.get("params") or {}
            if old.get("anchor") and self.sched.get("kind") == "interval" and old.get("seconds") == secs:
                params["anchor"] = old["anchor"]
        elif kind == "daily":
            times = [self.times.item(i).text() for i in range(self.times.count())]
            if not times:
                raise ValueError("Add at least one time of day (pick a time, then 'Add time').")
            days = [i for i, cb in enumerate(self.days) if cb.isChecked()]
            if not days:
                raise ValueError("Pick at least one day of the week.")
            params = {"times": times, "weekdays": [] if len(days) == 7 else days}
        else:
            params = {"at": iso(from_qdt(self.once_at.dateTime()))}
        start = iso(from_qdt(self.start_at.dateTime())) if self.use_start.isChecked() and kind != "once" else None
        end = iso(from_qdt(self.end_at.dateTime())) if self.use_end.isChecked() and kind != "once" else None
        if start and end and end <= start:
            raise ValueError("'Stop after' must be later than 'Start at'.")
        return kind, params, start, end

    def _preview(self, *a):
        try:
            kind, params, start, end = self._collect()
            now = datetime.now().astimezone()
            p = dict(params)
            if kind == "interval" and not start:
                p.setdefault("anchor", iso(now))
            nxt = sm.upcoming(kind, p, now, start, end, count=5)
            desc = sm.describe(kind, params, start, end)
            if nxt:
                self.preview.setText(f"<b>{desc}</b><br>Next sends: " + " • ".join(sm.fmt_dt(t) for t in nxt))
            else:
                self.preview.setText(f"<b>{desc}</b><br>⚠ No future send times — check the dates.")
        except ValueError as e:
            self.preview.setText(f"⚠ {e}")

    def _test(self):
        tid = self.target.currentData()
        msg = self.msg.toPlainText().strip()
        if tid is None or not msg:
            return error_box(self, "Test", "Pick a channel and write a message first.")
        self.test_b.setEnabled(False)

        def go():
            return self.engine.send_to_target(tid, msg, self.everyone.isChecked())

        def done(res, err):
            self.test_b.setEnabled(True)
            if err or not res.ok:
                return error_box(self, "Test failed", err or res.error)
            self.storage.update_target(tid, last_test_ok=1)
            self.engine.log.info("Discord", "Schedule test message sent.")
            info_box(self, "Sent", "Test message sent — check Discord.")

        run_async(go, on_done=done)

    def _save(self):
        try:
            kind, params, start, end = self._collect()
        except ValueError as e:
            return error_box(self, "Check the schedule", e)
        name = self.name.text().strip()
        s = {"job": self.job, "kind": kind, "params": params, "start_at": start, "end_at": end}
        if self.job == "message":
            tid = self.target.currentData()
            msg = self.msg.toPlainText().strip()
            if tid is None:
                return error_box(self, "Channel", "Add a Discord channel first (Discord Manager tab).")
            if not msg:
                return error_box(self, "Message", "Write the message to send.")
            if len(msg) > 2000:
                return error_box(self, "Message", "Discord allows at most 2000 characters.")
            s.update(target_id=tid, message=msg, allow_everyone=int(self.everyone.isChecked()),
                     name=name or msg[:30])
        else:
            mid = self.macro.currentData()
            if mid is None:
                return error_box(self, "Macro", "Save a macro first (Macro Recorder tab).")
            s.update(macro_id=mid, name=name or self.macro.currentText())
        if self.sched.get("id"):
            s["id"] = self.sched["id"]
        s["enabled"] = 0
        s["next_run_at"] = None
        self.result_id = self.storage.save_schedule(s)
        self.accept()


class SchedulerPage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        lay = page_layout(self, "Message Scheduler",
                          "Announcements are sent by this app even when no macro is running. Leave the app running "
                          "(it can sit in the system tray).")
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # messages tab
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 10, 0, 0)
        self.pause_b = button("", self._toggle_pause)
        v.addLayout(row(button("＋ New announcement", lambda: self._new("message"), kind="primary"),
                        button("Edit…", lambda: self._edit(self.msg_table)),
                        button("Duplicate", lambda: self._duplicate(self.msg_table)),
                        button("Delete", lambda: self._delete(self.msg_table)),
                        button("Send now", self._send_now, tip="Send the selected message right now (does not change its schedule)"),
                        button("Skip next", lambda: self._skip(self.msg_table)),
                        None, self.pause_b))
        self.msg_table = self._make_table(["On", "Name", "Channel", "Message", "Schedule", "Last sent", "Next send", "Status"])
        v.addWidget(self.msg_table, 1)
        v.addWidget(muted("Flip the switch to turn a message on or off. Double-click a row to edit it. "
                          "Tip for raids: make two daily messages, e.g. 5:30 PM “RAID IN 30 MINUTES!” and 6:00 PM “RAID TIME!”."))
        self.tabs.addTab(w, "Discord messages")

        # macros tab
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 10, 0, 0)
        self.resume_b = button("Resume macro schedules", self._resume_macros, kind="primary")
        v.addLayout(row(button("＋ Schedule a macro", lambda: self._new("macro"), kind="primary"),
                        button("Edit…", lambda: self._edit(self.mac_table)),
                        button("Delete", lambda: self._delete(self.mac_table)),
                        button("Skip next", lambda: self._skip(self.mac_table)),
                        None, self.resume_b))
        self.mac_banner = muted("")
        v.addWidget(self.mac_banner)
        self.mac_table = self._make_table(["On", "Name", "Macro", "Schedule", "Last run", "Next run", "Status"])
        v.addWidget(self.mac_table, 1)
        self.tabs.addTab(w, "Macro runs")

        engine.schedules_changed.connect(self.refresh)
        engine.state_changed.connect(self._update_buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.refresh()

    def _make_table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        t.itemChanged.connect(lambda it, t=t: self._item_changed(t, it))
        t.cellDoubleClicked.connect(lambda r, c, t=t: c != 0 and self._edit(t))
        return t

    # ---- refresh ------------------------------------------------------
    def refresh(self):
        self._next_cache = {}
        targets = {t["id"]: t["name"] for t in self.storage.list_targets()}
        macros = {m["id"]: m["name"] for m in self.storage.list_macros()}
        for table, job in ((self.msg_table, "message"), (self.mac_table, "macro")):
            sel = self._selected(table)
            rows = self.storage.list_schedules(job)
            table.blockSignals(True)
            table.setRowCount(len(rows))
            for r, s in enumerate(rows):
                on = QTableWidgetItem()
                on.setData(Qt.UserRole, s["id"])
                table.setItem(r, 0, on)
                sw = ToggleSwitch(bool(s["enabled"]))
                sw.toggled.connect(lambda v, sid=s["id"]: (self._set_enabled(sid, v), QTimer.singleShot(0, self.refresh)))
                holder = QWidget()
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(8, 0, 8, 0)
                hl.addWidget(sw)
                table.setCellWidget(r, 0, holder)
                desc = sm.describe(s["kind"], s["params"], s["start_at"], s["end_at"])
                status = STATUS_TEXT.get(s["last_status"], s["last_status"])
                if s["last_error"] and s["last_status"] in ("failed", "retrying"):
                    status += f": {s['last_error']}"
                nxt = parse_dt(s["next_run_at"]) if s["enabled"] else None
                self._next_cache[s["id"]] = nxt
                if job == "message":
                    msg = (s["message"] or "").replace("\n", " ")
                    vals = [s["name"], targets.get(s["target_id"], "⚠ missing channel"),
                            msg[:50] + ("…" if len(msg) > 50 else ""), desc,
                            sm.fmt_dt(parse_dt(s["last_run_at"])), relative(nxt) if nxt else "—", status]
                else:
                    vals = [s["name"], macros.get(s["macro_id"], "⚠ deleted"), desc,
                            sm.fmt_dt(parse_dt(s["last_run_at"])), relative(nxt) if nxt else "—", status]
                for c, v in enumerate(vals, start=1):
                    it = QTableWidgetItem(v)
                    it.setData(Qt.UserRole, s["id"])
                    if c == len(vals) and s["last_error"]:
                        it.setToolTip(s["last_error"])
                    table.setItem(r, c, it)
                if s["id"] == sel:
                    table.selectRow(r)
            table.blockSignals(False)
        self._update_buttons()

    def _tick(self):
        """Every second: update only the countdown column (no flicker)."""
        if not self.isVisible():
            return
        for table, col in ((self.msg_table, 6), (self.mac_table, 5)):
            for r in range(table.rowCount()):
                it = table.item(r, col)
                if it is None:
                    continue
                nxt = self._next_cache.get(it.data(Qt.UserRole))
                txt = relative(nxt) if nxt else "—"
                if it.text() != txt:
                    table.blockSignals(True)
                    it.setText(txt)
                    table.blockSignals(False)

    def _update_buttons(self):
        paused = self.engine.scheduler.messages_paused
        self.pause_b.setText("▶ Resume all messages" if paused else "⏸ Pause all messages")
        mp = self.engine.scheduler.macros_paused
        self.resume_b.setVisible(mp)
        self.mac_banner.setText("⚠ Macro schedules are paused because Emergency Stop was used. "
                                "Click 'Resume macro schedules' when you are ready." if mp else
                                "Scheduled macros press keys in whatever window is in front at that time.")

    def _selected(self, table):
        items = table.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    # ---- actions ------------------------------------------------------
    def _item_changed(self, table, item):
        if item.column() != 0:
            return
        sid = item.data(Qt.UserRole)
        want = item.checkState() == Qt.Checked
        self._set_enabled(sid, want)

    def _set_enabled(self, sid, want):
        s = self.storage.get_schedule(sid)
        if want and s["job"] == "message":
            t = self.storage.get_target(s["target_id"]) if s["target_id"] else None
            if not t:
                error_box(self, "No channel", "This message has no Discord channel. Edit it and pick one.")
                return self.refresh()
            if not t["last_test_ok"]:
                if confirm(self, "Send a test first?", f"The channel '{t['name']}' hasn't had a successful test "
                           "message yet. Send one now to make sure it works?", yes="Send test", no="Skip"):
                    def done(res, err):
                        if err or not res.ok:
                            error_box(self, "Test failed — schedule left off", err or res.error)
                            return self.refresh()
                        self._really_enable(sid)
                    run_async(self.engine.test_target, s["target_id"], on_done=done)
                    return
        if want:
            self._really_enable(sid)
        else:
            self.engine.scheduler.set_enabled(sid, False)

    def _really_enable(self, sid):
        try:
            self.engine.scheduler.set_enabled(sid, True)
        except ValueError as e:
            error_box(self, "Can't switch on", e)
        self.refresh()

    def _new(self, job):
        d = ScheduleDialog(self, self.engine, job)
        if d.exec() and d.result_id:
            if d.enable_cb.isChecked():
                self._set_enabled(d.result_id, True)
            self.refresh()

    def _edit(self, table):
        sid = self._selected(table)
        if not sid:
            return
        s = self.storage.get_schedule(sid)
        d = ScheduleDialog(self, self.engine, s["job"], s)
        if d.exec() and d.result_id:
            self.engine.scheduler.set_enabled(sid, False)
            if d.enable_cb.isChecked():
                self._set_enabled(sid, True)
            self.refresh()

    def _duplicate(self, table):
        sid = self._selected(table)
        if not sid:
            return
        s = self.storage.get_schedule(sid)
        s.pop("id")
        s.update(name=s["name"] + " (copy)", enabled=0, next_run_at=None, last_run_at=None,
                 last_status=None, last_error=None)
        s["params"] = {k: v for k, v in s["params"].items() if k != "anchor"}
        self.storage.save_schedule(s)
        self.refresh()

    def _delete(self, table):
        sid = self._selected(table)
        if not sid:
            return
        s = self.storage.get_schedule(sid)
        if confirm(self, "Delete", f"Delete '{s['name']}'?", yes="Delete"):
            self.storage.delete_schedule(sid)
            self.engine.log.info("Scheduler", f"Deleted schedule '{s['name']}'.")
            self.refresh()

    def _skip(self, table):
        sid = self._selected(table)
        if sid:
            self.engine.scheduler.skip_next(sid)

    def _send_now(self):
        sid = self._selected(self.msg_table)
        if not sid:
            return info_box(self, "Send now", "Select a message first.")
        s = self.storage.get_schedule(sid)
        if not confirm(self, "Send now", f"Send '{s['name']}' to Discord right now?", yes="Send"):
            return

        def done(res, err):
            if err or not res.ok:
                self.engine.log.error("Discord", f"Manual send of '{s['name']}' failed: {err or res.error}")
                return error_box(self, "Not sent", err or res.error)
            self.engine.log.info("Discord", f"Sent '{s['name']}' manually.")

        run_async(self.engine.send_to_target, s["target_id"], s["message"], bool(s["allow_everyone"]), on_done=done)

    def _toggle_pause(self):
        self.engine.set_messages_paused(not self.engine.scheduler.messages_paused)

    def _resume_macros(self):
        self.engine.resume_macro_schedules()


def _h(*ws):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in ws:
        h.addWidget(x)
    h.addStretch(1)
    return w
