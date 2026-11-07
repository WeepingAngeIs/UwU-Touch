"""Timeline Editor: every step with its delay and exact time, fully editable."""
from __future__ import annotations

import json

from PySide6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QDoubleSpinBox, QStyledItemDelegate, QButtonGroup, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QMenu, QRadioButton, QTableView, QToolButton, QWidget)

from ..core.models import ACTION_TYPES, Macro, PlaybackSettings, format_clock, parse_clock
from .action_dialog import ActionDialog
from .common import button, confirm, error_box, info_box, muted, page_layout

MIME = "application/x-novamacrohub-rows"
CLIP_MIME = "application/x-novamacrohub-steps"
COLS = ["#", "On", "", "Action", "Details", "Delay Before", "Timestamp"]
C_DELAY, C_TIME = 5, 6
ICONS = {"key_down": "⌨", "key_up": "⌨", "key_tap": "⌨", "mouse_move": "🖱", "mouse_down": "🖱", "mouse_up": "🖱",
         "mouse_click": "👆", "scroll": "↕", "wait": "⏱", "type_text": "🔤", "discord": "💬"}
TYPE_COLORS = {"key_down": "#4d8ff0", "key_up": "#4d8ff0", "key_tap": "#4d8ff0", "mouse_move": "#8a8f9c",
               "mouse_down": "#3dbb7a", "mouse_up": "#3dbb7a", "mouse_click": "#3dbb7a", "scroll": "#3dbb7a",
               "wait": "#e2a93b", "type_text": "#b07cf0", "discord": "#7289da"}


class StepModel(QAbstractTableModel):
    edit_failed = Signal(str)

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.unit_ms = False
        self._times = []

    @property
    def tl(self):
        return self.session.timeline

    def refresh(self):
        self.beginResetModel()
        self._times = self.tl.times()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tl.actions)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == C_DELAY:
                return f"Delay Before ({'ms' if self.unit_ms else 's'})"
            return COLS[section]
        return None

    def fmt_delay(self, d):
        return f"{d * 1000:.0f} ms" if self.unit_ms else f"{d:.2f} s"

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        a = self.tl.actions[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            if c == 0:
                return index.row() + 1
            if c == 2:
                return ICONS.get(a.type, "•")
            if c == 3:
                return a.title()
            if c == 4:
                return a.details()
            if c == C_DELAY:
                return self.fmt_delay(a.delay)
            if c == C_TIME:
                return format_clock(self._times[index.row()]) if index.row() < len(self._times) else ""
        if role == Qt.EditRole:
            if c == C_DELAY:
                return a.delay * (1000 if self.unit_ms else 1)
            if c == C_TIME:
                return format_clock(self._times[index.row()])
        if role == Qt.CheckStateRole and c == 1:
            return Qt.Checked if a.enabled else Qt.Unchecked
        if role == Qt.ForegroundRole:
            if not a.enabled:
                return QColor("#7d6f88")
            if c in (2, 3):
                return QColor(TYPE_COLORS.get(a.type, "#999"))
        if role == Qt.FontRole and c == 3 and a.type == "discord":
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ToolTipRole:
            if c == C_DELAY:
                return "Double-click to change the wait before this step. All later times update automatically."
            if c == C_TIME:
                return "Double-click to move this step to an exact time (mm:ss.cc or seconds)."
            return a.describe()
        if role == Qt.TextAlignmentRole and c in (0, 2):
            return int(Qt.AlignCenter)
        return None

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        if index.column() in (C_DELAY, C_TIME):
            base |= Qt.ItemIsEditable
        if index.column() == 1:
            base |= Qt.ItemIsUserCheckable
        return base

    def setData(self, index, value, role=Qt.EditRole):
        r, c = index.row(), index.column()
        try:
            if role == Qt.CheckStateRole and c == 1:
                checked = Qt.CheckState(value) == Qt.Checked if not isinstance(value, bool) else value
                self.tl.set_enabled([r], checked)
                self.session.emit_changed([r])
                return True
            if role != Qt.EditRole:
                return False
            if c == C_DELAY:
                v = float(str(value).replace(",", ".").strip().rstrip("ms").strip())
                self.tl.set_delay([r], v / 1000 if self.unit_ms else v)
            elif c == C_TIME:
                self.tl.set_time(r, parse_clock(str(value)))
            else:
                return False
        except ValueError as e:
            self.edit_failed.emit(str(e))
            return False
        self.session.emit_changed([r])
        return True

    # drag & drop (moves are applied by the view, see StepView.dropEvent)
    def supportedDropActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def supportedDragActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes})
        md = QMimeData()
        md.setData(MIME, json.dumps(rows).encode())
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIME)

    def dropMimeData(self, data, action, row, column, parent):
        return False


class DelayDelegate(QStyledItemDelegate):
    """Spin-box editor for the Delay Before column."""

    def __init__(self, model):
        super().__init__()
        self.m = model

    def createEditor(self, parent, option, index):
        sb = QDoubleSpinBox(parent)
        sb.setDecimals(0 if self.m.unit_ms else 3)
        sb.setRange(0, 7 * 24 * 3600 * (1000 if self.m.unit_ms else 1))
        sb.setSingleStep(100 if self.m.unit_ms else 0.1)
        sb.setSuffix(" ms" if self.m.unit_ms else " s")
        return sb

    def setEditorData(self, editor, index):
        editor.setValue(float(index.data(Qt.EditRole)))

    def setModelData(self, editor, model, index):
        editor.interpretText()
        model.setData(index, editor.value(), Qt.EditRole)


class StepView(QTableView):
    rows_dropped = Signal(list, int)

    def __init__(self, model=None):
        super().__init__()
        if model is not None:
            self.setModel(model)
            self.setItemDelegateForColumn(C_DELAY, DelayDelegate(model))
            self.setup_columns()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setWordWrap(False)

    def setup_columns(self):
        hh = self.horizontalHeader()
        for c, mode in ((0, QHeaderView.ResizeToContents), (1, QHeaderView.ResizeToContents),
                        (2, QHeaderView.ResizeToContents), (3, QHeaderView.Interactive), (4, QHeaderView.Stretch),
                        (C_DELAY, QHeaderView.Interactive), (C_TIME, QHeaderView.Interactive)):
            hh.setSectionResizeMode(c, mode)
        hh.resizeSection(3, 140)
        hh.resizeSection(C_DELAY, 130)
        hh.resizeSection(C_TIME, 100)

    def dragEnterEvent(self, e):
        if e.source() is self and e.mimeData().hasFormat(MIME):
            super().dragEnterEvent(e)
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self and e.mimeData().hasFormat(MIME):
            super().dragMoveEvent(e)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is not self or not e.mimeData().hasFormat(MIME):
            e.ignore()
            return
        rows = json.loads(bytes(e.mimeData().data(MIME)).decode())
        idx = self.indexAt(e.position().toPoint())
        pos = self.dropIndicatorPosition()
        n = self.model().rowCount()
        if not idx.isValid() or pos == QAbstractItemView.OnViewport:
            target = n
        elif pos == QAbstractItemView.BelowItem:
            target = idx.row() + 1
        else:
            target = idx.row()
        # Report CopyAction so Qt does not delete the "source" rows itself.
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.rows_dropped.emit(rows, target)


class TimelinePage(QWidget):
    play_selection = Signal(object)
    record_here = Signal(int)

    def __init__(self, engine, session):
        super().__init__()
        self.engine = engine
        self.session = session
        self.model = StepModel(session)
        lay = page_layout(self, "Timeline Editor",
                          "Every step of the macro. Double-click a delay or time to change it — all later times "
                          "move automatically. Drag rows to reorder. Right-click for more.")
        self.title = QLabel()
        self.title.setObjectName("h2")
        lay.addWidget(self.title)

        # toolbar
        tb = QHBoxLayout()
        tb.setSpacing(6)

        def tbtn(text, slot, tip, shortcut=None):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip + (f"  ({shortcut})" if shortcut else ""))
            b.clicked.connect(slot)
            b.setCursor(Qt.PointingHandCursor)
            tb.addWidget(b)
            if shortcut:
                act = QAction(self)
                act.setShortcut(QKeySequence(shortcut))
                act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
                act.triggered.connect(slot)
                self.addAction(act)
            return b

        self.undo_b = tbtn("↶ Undo", self.undo, "Undo", "Ctrl+Z")
        self.redo_b = tbtn("↷ Redo", self.redo, "Redo", "Ctrl+Y")
        tb.addSpacing(8)
        self.add_b = QToolButton()
        self.add_b.setText("＋ Add step ▾")
        self.add_b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        for k, label in ACTION_TYPES.items():
            menu.addAction(label, lambda k=k: self.add_step(k))
        self.add_b.setMenu(menu)
        self.add_b.setToolTip("Insert a new step after the selected row")
        tb.addWidget(self.add_b)
        tbtn("⏱ Insert delay", lambda: self.add_step("wait"), "Insert a wait period after the selected row")
        tbtn("✎ Edit", self.edit_selected, "Edit the selected step (or double-click it)")
        tbtn("⧉ Duplicate", self.duplicate, "Duplicate selected steps", "Ctrl+D")
        tbtn("Copy", self.copy, "Copy selected steps", "Ctrl+C")
        tbtn("Paste", self.paste, "Paste after the selected row", "Ctrl+V")
        tbtn("🗑 Delete", self.delete, "Delete selected steps", "Delete")
        tbtn("▲", self.move_up, "Move up", "Ctrl+Up")
        tbtn("▼", self.move_down, "Move down", "Ctrl+Down")
        tb.addSpacing(8)
        tbtn("⏱ Set delay…", self.set_delay_dialog, "Set the delay of all selected steps")
        tbtn("± Shift…", self.add_delay_dialog, "Add or remove time from the selected delays")
        tbtn("× Scale…", self.scale_dialog, "Multiply selected delays (e.g. 0.5 = twice as fast)")
        tb.addStretch(1)
        lay.addLayout(tb)

        tb2 = QHBoxLayout()
        tb2.setSpacing(6)
        tb2.addWidget(button("● Record into here", self._record_here,
                             tip="Record new actions and insert them after the selected row"))
        tb2.addWidget(button("▶ Play selected steps", self._play_sel, tip="Test only the selected rows"))
        tb2.addWidget(button("Thin mouse moves…", self.thin_dialog,
                             tip="Remove extra mouse-movement steps (keeps every click at its exact time)"))
        tb2.addStretch(1)
        tb2.addWidget(muted("Units:", wrap=False))
        self.unit_s = QRadioButton("seconds")
        self.unit_ms = QRadioButton("milliseconds")
        self.unit_s.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.unit_s)
        grp.addButton(self.unit_ms)
        self.unit_ms.toggled.connect(self._unit_changed)
        tb2.addWidget(self.unit_s)
        tb2.addWidget(self.unit_ms)
        self.save_b = button("💾 Save", self.save, kind="primary")
        tb2.addWidget(self.save_b)
        lay.addLayout(tb2)

        self.view = StepView(self.model)
        self.view.doubleClicked.connect(self._double_clicked)
        self.view.rows_dropped.connect(self._dropped)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        lay.addWidget(self.view, 1)

        self.footer = muted("", wrap=False)
        lay.addWidget(self.footer)

        self.model.edit_failed.connect(lambda m: error_box(self, "Can't change that", m))
        session.loaded.connect(lambda: self._refresh([]))
        session.changed.connect(self._refresh)
        session.saved.connect(lambda: self._refresh(self.selected_rows()))
        self._refresh([])

    # ---- helpers ------------------------------------------------------
    @property
    def tl(self):
        return self.session.timeline

    def selected_rows(self):
        return sorted({i.row() for i in self.view.selectionModel().selectedRows()})

    def _after_selection(self):
        rows = self.selected_rows()
        return rows[-1] + 1 if rows else len(self.tl)

    def _refresh(self, select_rows):
        self.model.refresh()
        m = self.session.macro
        self.title.setText(f"{m.name}{'  •  unsaved changes' if self.session.dirty else ''}")
        self.undo_b.setEnabled(self.tl.can_undo())
        self.redo_b.setEnabled(self.tl.can_redo())
        self.undo_b.setToolTip(f"Undo {self.tl.undo_label()} (Ctrl+Z)")
        self.redo_b.setToolTip(f"Redo {self.tl.redo_label()} (Ctrl+Y)")
        self._select(select_rows)
        self._selection_changed()

    def _select(self, rows):
        if not rows:
            return
        sm = self.view.selectionModel()
        sel = QItemSelection()
        for r in rows:
            if 0 <= r < self.model.rowCount():
                sel.select(self.model.index(r, 0), self.model.index(r, len(COLS) - 1))
        sm.select(sel, QItemSelectionModel.ClearAndSelect)
        if 0 <= rows[0] < self.model.rowCount():
            self.view.scrollTo(self.model.index(rows[0], 0))
            sm.setCurrentIndex(self.model.index(rows[0], 2), QItemSelectionModel.NoUpdate)

    def _selection_changed(self, *a):
        rows = self.selected_rows()
        times = self.tl.times()
        text = f"{len(self.tl)} steps  •  total length {format_clock(self.tl.total())}"
        if rows:
            span = times[rows[-1]] - (times[rows[0]] - self.tl.actions[rows[0]].delay)
            text += f"   |   {len(rows)} selected (rows {rows[0] + 1}–{rows[-1] + 1}), spanning {span:.3f}s"
            self.session.insert_row = rows[-1] + 1
        else:
            self.session.insert_row = None
        self.footer.setText(text)

    def _changed(self, rows):
        self.session.emit_changed(rows)

    def _unit_changed(self):
        self.model.unit_ms = self.unit_ms.isChecked()
        self.model.refresh()
        self._select(self.selected_rows())

    # ---- operations ---------------------------------------------------
    def undo(self):
        if self.tl.undo():
            self._changed([])

    def redo(self):
        if self.tl.redo():
            self._changed([])

    def add_step(self, type_):
        d = ActionDialog(self, self.engine.storage, default_type=type_)
        if d.exec() and d.result_action:
            rows = self.tl.insert(self._after_selection(), [d.result_action], label="Add step")
            self._changed(rows)

    def edit_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        self._edit(rows[0])

    def _edit(self, r):
        d = ActionDialog(self, self.engine.storage, self.tl.actions[r])
        if d.exec() and d.result_action:
            self.tl.replace(r, d.result_action)
            self._changed([r])

    def _double_clicked(self, idx):
        if idx.column() in (0, 2, 3, 4):
            self._edit(idx.row())

    def duplicate(self):
        self._changed(self.tl.duplicate(self.selected_rows()))

    def copy(self):
        rows = self.selected_rows()
        if not rows:
            return
        md = QMimeData()
        data = json.dumps(self.tl.copy(rows))
        md.setData(CLIP_MIME, data.encode())
        md.setText(data)
        QGuiApplication.clipboard().setMimeData(md)
        self.engine.log.info("Recording", f"Copied {len(rows)} step(s).")

    def paste(self):
        md = QGuiApplication.clipboard().mimeData()
        raw = bytes(md.data(CLIP_MIME)).decode() if md.hasFormat(CLIP_MIME) else md.text()
        try:
            steps = json.loads(raw)
            if isinstance(steps, dict) and "actions" in steps:
                steps = steps["actions"]
            if not isinstance(steps, list):
                raise ValueError
            rows = self.tl.paste(self._after_selection(), steps)
        except Exception:
            return info_box(self, "Paste", "The clipboard does not contain copied steps.")
        self._changed(rows)

    def delete(self):
        rows = self.selected_rows()
        if not rows:
            return
        self.tl.delete(rows)
        self._changed([min(rows[0], len(self.tl) - 1)] if len(self.tl) else [])

    def move_up(self):
        self._changed(self.tl.move_up(self.selected_rows()))

    def move_down(self):
        self._changed(self.tl.move_down(self.selected_rows()))

    def _dropped(self, rows, target):
        self._changed(self.tl.move(rows, target))

    def _need_selection(self):
        rows = self.selected_rows()
        if not rows:
            info_box(self, "Select steps", "Select one or more rows first (Ctrl+click or Shift+click for several).")
        return rows

    def set_delay_dialog(self):
        rows = self._need_selection()
        if not rows:
            return
        unit = "ms" if self.model.unit_ms else "seconds"
        cur = self.tl.actions[rows[0]].delay * (1000 if self.model.unit_ms else 1)
        v, ok = QInputDialog.getDouble(self, "Set delay", f"Delay before each of the {len(rows)} selected step(s), in {unit}:",
                                       cur, 0, 7 * 24 * 3600 * (1000 if self.model.unit_ms else 1), 3)
        if ok:
            self.tl.set_delay(rows, v / 1000 if self.model.unit_ms else v)
            self._changed(rows)

    def add_delay_dialog(self):
        rows = self._need_selection()
        if not rows:
            return
        unit = "ms" if self.model.unit_ms else "seconds"
        v, ok = QInputDialog.getDouble(self, "Shift delays", f"Add this many {unit} to each selected delay "
                                       "(negative to remove; delays never go below 0):", 0, -1e9, 1e9, 3)
        if ok:
            self.tl.add_to_delay(rows, v / 1000 if self.model.unit_ms else v)
            self._changed(rows)

    def scale_dialog(self):
        rows = self._need_selection()
        if not rows:
            return
        v, ok = QInputDialog.getDouble(self, "Scale delays", "Multiply the selected delays by:\n"
                                       "(2 = twice as slow, 0.5 = twice as fast)", 1.0, 0, 100, 3)
        if ok:
            self.tl.scale_delays(rows, v)
            self._changed(rows)

    def thin_dialog(self):
        v, ok = QInputDialog.getInt(self, "Thin mouse moves", "Keep at most one mouse-move step every … milliseconds\n"
                                    "(applies to the selection, or the whole macro if nothing is selected):",
                                    50, 5, 5000)
        if ok:
            n = self.tl.thin_moves(v / 1000, self.selected_rows() or None)
            self._changed([])
            info_box(self, "Thin mouse moves", f"Removed {n} mouse-move step(s). Clicks and key presses keep their exact times.")

    def _record_here(self):
        self.record_here.emit(self._after_selection())

    def _play_sel(self):
        rows = self.selected_rows()
        if not rows:
            return info_box(self, "Play selected", "Select the rows you want to test.")
        acts = [self.tl.actions[r].clone() for r in rows]
        acts[0].delay = 0.0
        self.play_selection.emit(Macro(self.session.macro.name + " (selection)", acts, PlaybackSettings()))

    def save(self):
        try:
            self.session.save()
        except ValueError as e:
            error_box(self, "Could not save", e)

    def _context_menu(self, pos):
        self._context_menu_at(self.view, pos)

    def _context_menu_at(self, view, pos):
        m = QMenu(self)
        rows = self.selected_rows()
        m.addAction("Edit step…", self.edit_selected).setEnabled(len(rows) == 1)
        sub = m.addMenu("Insert step after")
        for k, label in ACTION_TYPES.items():
            sub.addAction(label, lambda k=k: self.add_step(k))
        m.addSeparator()
        m.addAction("Set delay…", self.set_delay_dialog).setEnabled(bool(rows))
        m.addAction("Shift delays…", self.add_delay_dialog).setEnabled(bool(rows))
        m.addAction("Scale delays…", self.scale_dialog).setEnabled(bool(rows))
        m.addSeparator()
        m.addAction("Enable", lambda: (self.tl.set_enabled(rows, True), self._changed(rows))).setEnabled(bool(rows))
        m.addAction("Disable (skip)", lambda: (self.tl.set_enabled(rows, False), self._changed(rows))).setEnabled(bool(rows))
        m.addSeparator()
        m.addAction("Copy", self.copy).setEnabled(bool(rows))
        m.addAction("Paste", self.paste)
        m.addAction("Duplicate", self.duplicate).setEnabled(bool(rows))
        m.addAction("Delete", self.delete).setEnabled(bool(rows))
        m.addSeparator()
        m.addAction("Record into here…", self._record_here)
        m.addAction("Play selected steps", self._play_sel).setEnabled(bool(rows))
        m.exec(view.viewport().mapToGlobal(pos))
