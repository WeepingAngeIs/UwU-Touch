"""Small shared UI helpers."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..core import keynames


# ---- background work without freezing the window --------------------------
class _Signals(QObject):
    done = Signal(object, object)  # result, error


class _Job(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
            self.signals.done.emit(res, None)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.signals.done.emit(None, e)


_alive = set()


def run_async(fn, *args, on_done=None, **kwargs):
    """Run fn in a worker thread; call on_done(result, error) on the UI thread."""
    job = _Job(fn, args, kwargs)
    _alive.add(job.signals)

    def finished(res, err):
        _alive.discard(job.signals)
        if on_done:
            on_done(res, err)

    job.signals.done.connect(finished, Qt.QueuedConnection)
    QThreadPool.globalInstance().start(job)


# ---- widgets ----------------------------------------------------------------
def card(title: str | None = None, subtitle: str | None = None, icon: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel. If a title is given, `frame.header` is the title row so
    callers can add buttons on the right."""
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(9)
    if title:
        h = QHBoxLayout()
        h.setSpacing(8)
        if icon:
            ic = QLabel(icon)
            ic.setStyleSheet("font-size: 13pt;")
            h.addWidget(ic)
        t = QLabel(title)
        t.setObjectName("h2")
        h.addWidget(t)
        h.addStretch(1)
        lay.addLayout(h)
        f.header = h
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return f, lay


def button(text, slot=None, kind=None, tip=None, big=False) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if big and not kind:
        b.setProperty("kind", "big")
    if tip:
        b.setToolTip(tip)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def muted(text, wrap=True) -> QLabel:
    l = QLabel(text)
    l.setObjectName("muted")
    l.setWordWrap(wrap)
    return l


def heading(text) -> QLabel:
    l = QLabel(text)
    l.setObjectName("h1")
    return l


def page_layout(widget: QWidget, title: str, subtitle: str = "") -> QVBoxLayout:
    widget.setObjectName("page")
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(14)
    lay.addWidget(heading(title))
    if subtitle:
        lay.addWidget(muted(subtitle))
    return lay


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: rgba(128,128,128,60)")
    return f


def error_box(parent, title, text):
    QMessageBox.warning(parent, title, str(text))


def info_box(parent, title, text):
    QMessageBox.information(parent, title, str(text))


def confirm(parent, title, text, yes="Yes", no="Cancel") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    y = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is y


def set_pill(label: QLabel, text: str, state: str):
    label.setText(text)
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)


CURRENT_THEME = {"name": "dark"}


def paint_cat(p: QPainter, x: float, y: float, size: float, face="#ffffff", line="#1b0b22", blush="#ff7ac3"):
    """Draw an original round kawaii cat face (our logo)."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPen, QPolygonF
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    pen = QPen(QColor(line), max(1.5, s * 0.045))
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(face))
    for side in (-1, 1):  # ears
        cx = x + s / 2 + side * s * 0.27
        p.drawPolygon(QPolygonF([QPointF(cx - s * 0.17, y + s * 0.36), QPointF(cx + side * s * 0.08, y + s * 0.04),
                                 QPointF(cx + s * 0.17, y + s * 0.36)]))
    p.drawEllipse(QRectF(x + s * 0.08, y + s * 0.22, s * 0.84, s * 0.70))
    p.setBrush(QColor(blush))
    p.setPen(Qt.NoPen)
    for side in (-1, 1):
        cx = x + s / 2 + side * s * 0.27
        p.drawPolygon(QPolygonF([QPointF(cx - s * 0.08, y + s * 0.30), QPointF(cx + side * s * 0.05, y + s * 0.13),
                                 QPointF(cx + s * 0.08, y + s * 0.30)]))
        p.drawEllipse(QRectF(x + s / 2 + side * s * 0.25 - s * 0.07, y + s * 0.64, s * 0.14, s * 0.07))
    p.setBrush(QColor(line))
    for side in (-1, 1):  # eyes
        p.drawEllipse(QRectF(x + s / 2 + side * s * 0.17 - s * 0.055, y + s * 0.47, s * 0.11, s * 0.13))
    p.setBrush(QColor("white"))
    for side in (-1, 1):
        p.drawEllipse(QRectF(x + s / 2 + side * s * 0.17 - s * 0.02, y + s * 0.49, s * 0.04, s * 0.04))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    mx, my = x + s / 2, y + s * 0.66
    p.drawArc(QRectF(mx - s * 0.08, my - s * 0.04, s * 0.08, s * 0.08), 180 * 16, 180 * 16)
    p.drawArc(QRectF(mx, my - s * 0.04, s * 0.08, s * 0.08), 180 * 16, 180 * 16)
    thin = QPen(QColor(line), max(1.0, s * 0.025))
    p.setPen(thin)
    for side in (-1, 1):  # whiskers
        for dy in (-0.03, 0.03):
            p.drawLine(QPointF(mx + side * s * 0.22, my + s * dy), QPointF(mx + side * s * 0.42, my + s * dy * 2))
    p.restore()


def app_icon(size=256) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(size * 0.03, size * 0.03, size * 0.94, size * 0.94, size * 0.24, size * 0.24)
    from PySide6.QtGui import QLinearGradient
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor("#ff70b8"))
    g.setColorAt(1, QColor("#7b3cf0"))
    p.fillPath(path, g)
    paint_cat(p, size * 0.12, size * 0.10, size * 0.76)
    p.end()
    return QIcon(pm)


def tray_icon(state: str) -> QIcon:
    """Small icon with a colored dot: idle / rec / play."""
    base = app_icon(64).pixmap(64, 64)
    if state == "idle":
        return QIcon(base)
    p = QPainter(base)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#ff3d6e" if state == "rec" else "#2bd47a"))
    p.setPen(QColor("white"))
    p.drawEllipse(34, 34, 28, 28)
    p.end()
    return QIcon(base)


class CatLogo(QWidget):
    def __init__(self, size=58):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, e):
        p = QPainter(self)
        paint_cat(p, 0, 0, self.width())
        p.end()


class ToggleSwitch(QWidget):
    """An iOS-style on/off switch."""
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setFixedSize(42, 22)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, v, emit=False):
        v = bool(v)
        if v != self._checked:
            self._checked = v
            self.update()
            if emit:
                self.toggled.emit(v)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.setChecked(not self._checked, emit=True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2bd47a" if self._checked else "#5b4a66"))
        p.drawRoundedRect(self.rect(), 11, 11)
        p.setBrush(QColor("white"))
        x = self.width() - 20 if self._checked else 2
        p.drawEllipse(x, 2, 18, 18)
        p.end()


class Backdrop(QWidget):
    """Window background: a night gradient with cherry blossoms, or the user's own image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_path = None
        self._pix = None
        self._cache = None

    def set_image(self, path):
        self.image_path = path or None
        self._pix = QPixmap(path) if path else None
        if self._pix is not None and self._pix.isNull():
            self._pix = None
        self._cache = None
        self.update()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def refresh_theme(self):
        self._cache = None
        self.update()

    def paintEvent(self, e):
        if self._cache is None or self._cache.size() != self.size():
            self._cache = self._render()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.end()

    def _render(self):
        import random
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QLinearGradient, QRadialGradient
        from .theme import PALETTES
        c = PALETTES[CURRENT_THEME["name"]]
        w, h = max(1, self.width()), max(1, self.height())
        pm = QPixmap(w, h)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QColor(c["bg2"]))
        g.setColorAt(0.5, QColor(c["bg"]))
        g.setColorAt(1, QColor(c["bg2"]))
        p.fillRect(0, 0, w, h, g)
        if self._pix is not None:
            scaled = self._pix.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
            veil = QColor(c["bg"])
            veil.setAlpha(110)
            p.fillRect(0, 0, w, h, veil)
            p.end()
            return pm
        rnd = random.Random(7)
        # blossom clusters along the top edge and the bottom corners
        anchors = [(x, rnd.uniform(-20, 60)) for x in range(0, w + 120, 110)]
        anchors += [(rnd.uniform(-40, 220), h - rnd.uniform(0, 160)) for _ in range(8)]
        anchors += [(w - rnd.uniform(-40, 220), h - rnd.uniform(0, 160)) for _ in range(8)]
        for ax, ay in anchors:
            for _ in range(9):
                r = rnd.uniform(10, 30)
                cx, cy = ax + rnd.uniform(-60, 60), ay + rnd.uniform(-35, 35)
                col = QColor(c["blossom"] if rnd.random() < 0.7 else c["blossom2"])
                rg = QRadialGradient(QPointF(cx, cy), r)
                col.setAlpha(150)
                rg.setColorAt(0, col)
                col2 = QColor(col)
                col2.setAlpha(0)
                rg.setColorAt(1, col2)
                p.setBrush(rg)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(cx, cy), r, r)
        petal = QColor(c["blossom"])
        petal.setAlpha(170)
        p.setBrush(petal)
        for _ in range(int(w * h / 26000)):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            p.save()
            p.translate(x, y)
            p.rotate(rnd.uniform(0, 360))
            p.drawEllipse(QPointF(0, 0), rnd.uniform(3, 6), rnd.uniform(1.5, 3))
            p.restore()
        p.end()
        return pm


# ---- hotkey / key capture ---------------------------------------------------
QT_KEY_NAMES = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Tab: "tab",
    Qt.Key_Backspace: "backspace", Qt.Key_Escape: "esc", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert",
    Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_PageUp: "page_up", Qt.Key_PageDown: "page_down",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Pause: "pause", Qt.Key_Print: "print_screen", Qt.Key_CapsLock: "caps_lock",
    Qt.Key_NumLock: "num_lock", Qt.Key_ScrollLock: "scroll_lock", Qt.Key_Menu: "menu",
    Qt.Key_Semicolon: ";", Qt.Key_Equal: "=", Qt.Key_Comma: ",", Qt.Key_Minus: "-", Qt.Key_Period: ".",
    Qt.Key_Slash: "/", Qt.Key_QuoteLeft: "`", Qt.Key_BracketLeft: "[", Qt.Key_Backslash: "\\",
    Qt.Key_BracketRight: "]", Qt.Key_Apostrophe: "'",
}
MOD_KEYS = {Qt.Key_Shift: "shift", Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt", Qt.Key_Meta: "cmd"}


def qt_key_to_name(event) -> str | None:
    k = event.key()
    if Qt.Key_F1 <= k <= Qt.Key_F24:
        return f"f{k - Qt.Key_F1 + 1}"
    if Qt.Key_A <= k <= Qt.Key_Z:
        return chr(k).lower()
    if Qt.Key_0 <= k <= Qt.Key_9:
        if event.modifiers() & Qt.KeypadModifier:
            return f"num_{chr(k)}"
        return chr(k)
    if k in QT_KEY_NAMES:
        return QT_KEY_NAMES[k]
    if k in MOD_KEYS:
        return MOD_KEYS[k]
    vk = event.nativeVirtualKey()
    if vk:
        return keynames.name_for_vk(vk)
    return None


class KeyCaptureDialog(QDialog):
    """Press a key (or combo). Returns e.g. 'ctrl+shift+f9' (hotkey mode) or 'w'."""

    def __init__(self, parent=None, hotkey_mode=True, title="Press a key"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.hotkey_mode = hotkey_mode
        self.result_text = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        msg = ("Press the key combination you want (for example F9 or Ctrl+Shift+R)."
               if hotkey_mode else "Press the key you want this step to use.")
        lay.addWidget(muted(msg))
        self.preview = QLabel("waiting…")
        self.preview.setObjectName("bigclock")
        self.preview.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(380)

    def keyPressEvent(self, e):
        name = qt_key_to_name(e)
        if not name:
            return
        if self.hotkey_mode:
            if name in ("shift", "ctrl", "alt", "cmd"):
                mods = self._mods(e)
                self.preview.setText(" + ".join(m.title() for m in mods) + " + …")
                return
            mods = self._mods(e)
            self.result_text = "+".join(mods + [name])
        else:
            self.result_text = name
        self.preview.setText(keynames.hotkey_label(self.result_text) if self.hotkey_mode else keynames.pretty(name))
        self.accept()

    @staticmethod
    def _mods(e):
        m = e.modifiers()
        out = []
        if m & Qt.ControlModifier:
            out.append("ctrl")
        if m & Qt.ShiftModifier:
            out.append("shift")
        if m & Qt.AltModifier:
            out.append("alt")
        return out


class Spacer(QWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


def row(*widgets, stretch_last=False, spacing=8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            h.addLayout(w)
        else:
            h.addWidget(w)
    if stretch_last:
        h.addStretch(1)
    return h
