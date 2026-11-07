"""Dialog to create or edit one timeline step."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..core import keynames
from ..core.models import ACTION_TYPES, BUTTON_NAMES, Action
from .common import KeyCaptureDialog, error_box, muted


def cursor_pos():
    """Current mouse position in real screen pixels (same units the recorder uses)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    p = QCursor.pos()
    return p.x(), p.y()


class ActionEditor(QWidget):
    """The step editor form. Used inline (dashboard Action Editor) and in ActionDialog."""

    def __init__(self, storage, action: Action | None = None, default_type="key_tap", compact=False, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.compact = compact
        a = action or Action(default_type, 0.5 if default_type != "wait" else 1.0, {})
        self._orig = a

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        if compact:
            form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.type_cb = QComboBox()
        for k, label in ACTION_TYPES.items():
            self.type_cb.addItem(label, k)
        form.addRow("Action type", self.type_cb)
        lay.addLayout(form)

        self.stack = QStackedWidget()
        self.pages = {}
        self._build_pages(a)
        lay.addWidget(self.stack)

        f2 = QFormLayout()
        self.delay = QDoubleSpinBox()
        self.delay.setDecimals(3)
        self.delay.setRange(0, 7 * 24 * 3600 * 1000)
        self.delay.setSingleStep(0.1)
        self.delay_unit = QComboBox()
        self.delay_unit.addItem("seconds", 1.0)
        self.delay_unit.addItem("milliseconds", 0.001)
        self.delay_unit.currentIndexChanged.connect(self._unit_changed)
        self._unit = 1.0
        self.delay.setToolTip("How long to wait before this step happens.")
        f2.addRow("Delay before", _hbox(self.delay, self.delay_unit))
        lay.addLayout(f2)

        self.enabled = QCheckBox("Step enabled" if compact else "Step enabled (unticked = skipped, timing kept)")
        self.enabled.setToolTip("Unticked steps are skipped but keep their timing")
        lay.addWidget(self.enabled)
        self.type_cb.currentIndexChanged.connect(self._type_changed)
        if compact:
            for fl in self.findChildren(QFormLayout):
                fl.setRowWrapPolicy(QFormLayout.WrapAllRows)
            f2.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.load(a)

    def load(self, a: Action):
        """Show an existing step in the form."""
        self._orig = a
        self.type_cb.blockSignals(True)
        self.type_cb.setCurrentIndex(list(ACTION_TYPES).index(a.type))
        self.type_cb.blockSignals(False)
        p = a.params
        self.key.setCurrentText(p.get("key", "space"))
        self.hold.setValue(int(p.get("hold_ms", 50)))
        self.btn.setCurrentIndex(max(0, self.btn.findData(p.get("button", "left"))))
        self.mx.setValue(int(p.get("x", 0)))
        self.my.setValue(int(p.get("y", 0)))
        self.count.setValue(int(p.get("count", 1)))
        self.sdy.setValue(int(p.get("dy", -1)))
        self.sdx.setValue(int(p.get("dx", 0)))
        self.note.setText(p.get("note", ""))
        self.text.setPlainText(p.get("text", ""))
        self.reload_targets(p.get("target_id"))
        self.dmsg.setPlainText(p.get("message", ""))
        self.everyone.setChecked(bool(p.get("allow_everyone")))
        self.delay.setValue(a.delay / self._unit)
        self.enabled.setChecked(a.enabled)
        self.pos_status.setText("")
        self._type_changed()

    def reload_targets(self, select=None):
        select = select if select is not None else self.target.currentData()
        self.target.clear()
        for t in self.storage.list_targets():
            self.target.addItem(f"{t['name']}  ({'Webhook' if t['kind'] == 'webhook' else 'Bot'})", t["id"])
        if self.target.count() == 0:
            self.target.addItem("No channels yet — add one in Discord Manager", None)
        i = self.target.findData(select)
        if i >= 0:
            self.target.setCurrentIndex(i)

    def _unit_changed(self):
        secs = self.delay.value() * self._unit
        self._unit = self.delay_unit.currentData()
        self.delay.setValue(secs / self._unit)

    # ---- pages --------------------------------------------------------
    def _build_pages(self, a: Action):
        p = a.params
        # key page
        w = QWidget(); f = QFormLayout(w)
        self.key = QComboBox(); self.key.setEditable(True)
        names = sorted(keynames.VK_BY_NAME, key=lambda n: (len(n) > 1, n))
        self.key.addItems(names)
        self.key.setCurrentText(p.get("key", "space"))
        pick = QPushButton("Press a key…")
        pick.clicked.connect(self._pick_key)
        f.addRow("Key", _hbox(self.key, pick))
        self.hold = QSpinBox(); self.hold.setRange(1, 60000); self.hold.setSuffix(" ms")
        self.hold.setValue(int(p.get("hold_ms", 50)))
        self.hold_row_label = QLabel("Hold for")
        f.addRow(self.hold_row_label, self.hold)
        self._add_page("key", w)

        # mouse page
        w = QWidget(); f = QFormLayout(w)
        self.btn = QComboBox()
        for k, label in BUTTON_NAMES.items():
            self.btn.addItem(label, k)
        idx = self.btn.findData(p.get("button", "left"))
        self.btn.setCurrentIndex(max(0, idx))
        self.btn_label = QLabel("Button")
        f.addRow(self.btn_label, self.btn)
        self.mx = QSpinBox(); self.mx.setRange(-100000, 100000); self.mx.setValue(int(p.get("x", 0)))
        self.my = QSpinBox(); self.my.setRange(-100000, 100000); self.my.setValue(int(p.get("y", 0)))
        pickpos = QPushButton("Pick position (3 s countdown)")
        pickpos.setToolTip("Click, then move the mouse to the spot within 3 seconds.")
        pickpos.clicked.connect(self._pick_pos)
        self.pos_status = muted("")
        f.addRow("Position X / Y", _hbox(self.mx, self.my))
        f.addRow("", pickpos)
        f.addRow("", self.pos_status)
        self.count = QSpinBox(); self.count.setRange(1, 10); self.count.setValue(int(p.get("count", 1)))
        self.count_label = QLabel("Clicks")
        f.addRow(self.count_label, self.count)
        self.sdy = QSpinBox(); self.sdy.setRange(-100, 100); self.sdy.setValue(int(p.get("dy", -1)))
        self.sdx = QSpinBox(); self.sdx.setRange(-100, 100); self.sdx.setValue(int(p.get("dx", 0)))
        self.sdy_label = QLabel("Scroll up(+)/down(−)")
        self.sdx_label = QLabel("Scroll right(+)/left(−)")
        f.addRow(self.sdy_label, self.sdy)
        f.addRow(self.sdx_label, self.sdx)
        self._add_page("mouse", w)

        # wait page
        w = QWidget(); f = QFormLayout(w)
        self.note = QLineEdit(p.get("note", ""))
        self.note.setPlaceholderText("optional label, e.g. 'wait for loading screen'")
        f.addRow(muted("A pause that does nothing. Set its length with 'Wait before' above."))
        f.addRow("Label", self.note)
        self._add_page("wait", w)

        # text page
        w = QWidget(); f = QFormLayout(w)
        self.text = QPlainTextEdit(p.get("text", ""))
        self.text.setPlaceholderText("Text to type into the focused window (new lines press Enter)")
        self.text.setFixedHeight(70 if self.compact else 90)
        f.addRow("Text", self.text)
        self._add_page("text", w)

        # discord page
        w = QWidget(); f = QFormLayout(w)
        self.target = QComboBox()
        self.dmsg = QPlainTextEdit(p.get("message", ""))
        self.dmsg.setPlaceholderText("Raid starts in 10 minutes!")
        self.dmsg.setFixedHeight(70 if self.compact else 90)
        self.everyone = QCheckBox("Allow @everyone / @here pings")
        self.everyone.setChecked(bool(p.get("allow_everyone")))
        f.addRow("Channel", self.target)
        f.addRow("Message", self.dmsg)
        f.addRow("", self.everyone)
        self._add_page("discord", w)

    def _add_page(self, name, w):
        self.pages[name] = self.stack.addWidget(w)

    def _type_changed(self):
        t = self.type_cb.currentData()
        page = {"key_down": "key", "key_up": "key", "key_tap": "key", "wait": "wait", "type_text": "text",
                "discord": "discord"}.get(t, "mouse")
        self.stack.setCurrentIndex(self.pages[page])
        from PySide6.QtWidgets import QSizePolicy
        for i in range(self.stack.count()):  # size the stack to the visible page only
            pol = QSizePolicy.Preferred if i == self.pages[page] else QSizePolicy.Ignored
            self.stack.widget(i).setSizePolicy(pol, pol)
        self.stack.adjustSize()
        self.hold.setVisible(t == "key_tap"); self.hold_row_label.setVisible(t == "key_tap")
        is_btn = t in ("mouse_down", "mouse_up", "mouse_click")
        self.btn.setVisible(is_btn); self.btn_label.setVisible(is_btn)
        self.count.setVisible(t == "mouse_click"); self.count_label.setVisible(t == "mouse_click")
        for wdg in (self.sdy, self.sdx, self.sdy_label, self.sdx_label):
            wdg.setVisible(t == "scroll")

    def _pick_key(self):
        d = KeyCaptureDialog(self, hotkey_mode=False)
        if d.exec() and d.result_text:
            self.key.setCurrentText(d.result_text)

    def _pick_pos(self):
        self._countdown = 3
        self.pos_status.setText("Move the mouse to the spot… 3")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_pos)
        self._timer.start(1000)

    def _tick_pos(self):
        self._countdown -= 1
        if self._countdown > 0:
            self.pos_status.setText(f"Move the mouse to the spot… {self._countdown}")
            return
        self._timer.stop()
        x, y = cursor_pos()
        self.mx.setValue(x)
        self.my.setValue(y)
        self.pos_status.setText(f"Captured ({x}, {y})")
        self.window().raise_()
        self.window().activateWindow()

    # ---- result -------------------------------------------------------
    def build(self) -> Action:
        """Return the edited step. Raises ValueError with a friendly message."""
        t = self.type_cb.currentData()
        params = {}
        if t in ("key_down", "key_up", "key_tap"):
            key = self.key.currentText().strip().lower()
            if not keynames.is_known(key):
                raise ValueError(f"'{key}' is not a key name. Use 'Press a key…'.")
            params["key"] = key
            if t == "key_tap":
                params["hold_ms"] = self.hold.value()
        elif t in ("mouse_move", "mouse_down", "mouse_up", "mouse_click", "scroll"):
            params.update(x=self.mx.value(), y=self.my.value())
            if t in ("mouse_down", "mouse_up", "mouse_click"):
                params["button"] = self.btn.currentData()
            if t == "mouse_click":
                params["count"] = self.count.value()
            if t == "scroll":
                params.update(dx=self.sdx.value(), dy=self.sdy.value())
                if not params["dx"] and not params["dy"]:
                    raise ValueError("Set a scroll amount other than 0.")
        elif t == "wait":
            if self.note.text().strip():
                params["note"] = self.note.text().strip()
        elif t == "type_text":
            if not self.text.toPlainText():
                raise ValueError("Enter some text to type.")
            params["text"] = self.text.toPlainText()
        elif t == "discord":
            tid = self.target.currentData()
            msg = self.dmsg.toPlainText().strip()
            if tid is None:
                raise ValueError("Add a Discord channel first (Discord Manager tab).")
            if not msg:
                raise ValueError("Write the message to send.")
            if len(msg) > 2000:
                raise ValueError("Discord messages can be at most 2000 characters.")
            t_row = self.storage.get_target(tid)
            params.update(target_id=tid, target_name=t_row["name"] if t_row else "", message=msg,
                          allow_everyone=self.everyone.isChecked())
        a = Action(t, round(self.delay.value() * self._unit, 6), params, self.enabled.isChecked())
        a.id = self._orig.id
        return a


class ActionDialog(QDialog):
    def __init__(self, parent, storage, action: Action | None = None, default_type="key_tap"):
        super().__init__(parent)
        self.setWindowTitle("Edit step" if action else "Add step")
        self.setMinimumWidth(480)
        self.result_action = None
        lay = QVBoxLayout(self)
        self.editor = ActionEditor(storage, action, default_type)
        lay.addWidget(self.editor)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        try:
            self.result_action = self.editor.build()
        except ValueError as e:
            return error_box(self, "Check this step", e)
        self.accept()


def _hbox(*ws):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in ws:
        h.addWidget(x)
    return w
