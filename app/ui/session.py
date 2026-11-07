"""The macro currently open in the Recorder and Timeline Editor."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.models import Macro
from ..core.timeline import Timeline


class MacroSession(QObject):
    loaded = Signal()          # a different macro was opened
    changed = Signal(list)     # steps changed; list = rows to select afterwards
    saved = Signal()
    list_changed = Signal()    # saved macro list changed (names, add, delete)
    playback_changed = Signal(object)  # sender widget, after repeat/speed/loop settings change

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        self.timeline = Timeline(Macro(self.storage.unique_macro_name("New macro")))
        self.insert_row: int | None = None   # where "record into timeline" inserts
        last = self.storage.get_setting("last_macro_id")
        if last:
            m = self.storage.load_macro(last)
            if m:
                self.timeline.load(m)

    @property
    def macro(self) -> Macro:
        return self.timeline.macro

    @property
    def dirty(self) -> bool:
        return self.timeline.dirty

    def emit_changed(self, rows=None):
        self.changed.emit(list(rows or []))

    def new(self, name=None):
        self.timeline.load(Macro(self.storage.unique_macro_name(name or "New macro")))
        self.timeline.dirty = False
        self.insert_row = None
        self.loaded.emit()

    def open(self, macro_id):
        m = self.storage.load_macro(macro_id)
        if not m:
            raise ValueError("That macro no longer exists.")
        self.timeline.load(m)
        self.insert_row = None
        self.storage.set_setting("last_macro_id", m.id)
        self.loaded.emit()

    def save(self):
        self.storage.save_macro(self.macro)
        self.timeline.mark_saved()
        self.storage.set_setting("last_macro_id", self.macro.id)
        self.engine.log.info("Recording", f"Saved macro '{self.macro.name}' ({len(self.macro.actions)} steps).")
        self.saved.emit()
        self.list_changed.emit()

    def rename(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Name cannot be empty.")
        old = self.macro.name
        self.macro.name = name
        try:
            if self.macro.id is not None:
                self.storage.save_macro(self.macro)
        except Exception:
            self.macro.name = old
            raise
        self.list_changed.emit()
        self.loaded.emit()

    def delete_current(self):
        if self.macro.id is not None:
            self.storage.delete_macro(self.macro.id)
            self.engine.log.info("Recording", f"Deleted macro '{self.macro.name}'.")
        self.storage.set_setting("last_macro_id", None)
        self.list_changed.emit()
        rest = self.storage.list_macros()
        if rest:
            self.open(rest[0]["id"])
        else:
            self.new()

    def export_json(self, path):
        data = self.macro.to_dict()
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        self.engine.log.info("Recording", f"Exported '{self.macro.name}' to {path}")

    def import_json(self, path) -> Macro:
        try:
            data = json.loads(Path(path).read_text("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"The file is not valid JSON ({e}).") from e
        m = Macro.from_dict(data)
        # Discord steps point at channel IDs from another computer: keep them, but
        # warn if the channel does not exist here.
        known = {t["id"] for t in self.storage.list_targets()}
        missing = sum(1 for a in m.actions if a.type == "discord" and a.params.get("target_id") not in known)
        m.name = self.storage.unique_macro_name(m.name)
        self.storage.save_macro(m)
        self.engine.log.info("Recording", f"Imported macro '{m.name}' ({len(m.actions)} steps).")
        self.list_changed.emit()
        self.open(m.id)
        m.missing_channels = missing
        return m
