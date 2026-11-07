"""Timeline editing with undo/redo.

Every action stores only the delay BEFORE it; timestamps are always derived from
the delays, so changing any delay automatically shifts every later timestamp.
"""
from __future__ import annotations

from .models import Action, Macro, timestamps

MAX_UNDO = 200


class Timeline:
    def __init__(self, macro: Macro | None = None):
        self.macro = macro or Macro(name="Untitled")
        self._undo: list[tuple[str, list]] = []
        self._redo: list[tuple[str, list]] = []
        self.dirty = False

    # ---- basics -------------------------------------------------------
    @property
    def actions(self) -> list[Action]:
        return self.macro.actions

    def __len__(self):
        return len(self.macro.actions)

    def times(self) -> list[float]:
        return timestamps(self.macro.actions)

    def total(self) -> float:
        return self.macro.total_duration()

    def load(self, macro: Macro):
        self.macro = macro
        self._undo.clear()
        self._redo.clear()
        self.dirty = False

    # ---- undo / redo --------------------------------------------------
    def _snapshot(self):
        return [a.clone(keep_id=True) for a in self.macro.actions]

    def _push(self, label: str):
        self._undo.append((label, self._snapshot()))
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo_label(self):
        return self._undo[-1][0] if self._undo else ""

    def redo_label(self):
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> bool:
        if not self._undo:
            return False
        label, snap = self._undo.pop()
        self._redo.append((label, self._snapshot()))
        self.macro.actions = snap
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        label, snap = self._redo.pop()
        self._undo.append((label, self._snapshot()))
        self.macro.actions = snap
        self.dirty = True
        return True

    # ---- edits --------------------------------------------------------
    @staticmethod
    def _check_delay(value: float) -> float:
        value = float(value)
        if value < 0:
            raise ValueError("Delay cannot be negative")
        if value > 7 * 24 * 3600:
            raise ValueError("Delay is longer than a week")
        return round(value, 6)

    def set_delay(self, rows, seconds: float):
        seconds = self._check_delay(seconds)
        rows = self._valid(rows)
        if not rows:
            return
        self._push("Change delay")
        for r in rows:
            self.actions[r].delay = seconds

    def add_to_delay(self, rows, seconds: float):
        rows = self._valid(rows)
        if not rows:
            return
        self._push("Adjust delay")
        for r in rows:
            self.actions[r].delay = max(0.0, round(self.actions[r].delay + float(seconds), 6))

    def scale_delays(self, rows, factor: float):
        factor = float(factor)
        if factor < 0:
            raise ValueError("Scale factor cannot be negative")
        rows = self._valid(rows)
        if not rows:
            return
        self._push("Scale delays")
        for r in rows:
            self.actions[r].delay = round(self.actions[r].delay * factor, 6)

    def set_time(self, row: int, at_seconds: float):
        """Move one action to an exact timestamp by changing its own delay.
        Later actions keep their delays, so they all shift by the same amount."""
        row = self._valid([row])[0]
        prev = self.times()[row - 1] if row > 0 else 0.0
        if at_seconds < prev - 1e-9:
            raise ValueError(f"Time must be at or after the previous step ({prev:.3f}s)")
        self._push("Change time")
        self.actions[row].delay = round(at_seconds - prev, 6)

    def insert(self, row: int, actions: list[Action], label="Insert"):
        if not actions:
            return []
        row = max(0, min(row, len(self.actions)))
        self._push(label)
        new = [a.clone() for a in actions]
        self.actions[row:row] = new
        return list(range(row, row + len(new)))

    def replace_all(self, actions: list[Action], label="Record"):
        self._push(label)
        self.macro.actions = [a.clone() for a in actions]
        return list(range(len(self.macro.actions)))

    def delete(self, rows):
        rows = sorted(set(self._valid(rows)), reverse=True)
        if not rows:
            return
        self._push("Delete")
        for r in rows:
            del self.actions[r]

    def duplicate(self, rows):
        rows = sorted(set(self._valid(rows)))
        if not rows:
            return []
        copies = [self.actions[r].clone() for r in rows]
        return self.insert(rows[-1] + 1, copies, label="Duplicate")

    def copy(self, rows) -> list[dict]:
        return [self.actions[r].to_dict() for r in sorted(set(self._valid(rows)))]

    def paste(self, row: int, clipboard: list[dict]):
        acts = [Action.from_dict({**d, "id": None}) for d in clipboard]
        return self.insert(row, acts, label="Paste")

    def replace(self, row: int, action: Action):
        row = self._valid([row])[0]
        self._push("Edit action")
        action = action.clone(keep_id=True)
        action.delay = self._check_delay(action.delay)
        self.actions[row] = action

    def set_enabled(self, rows, enabled: bool):
        rows = self._valid(rows)
        if not rows:
            return
        self._push("Enable" if enabled else "Disable")
        for r in rows:
            self.actions[r].enabled = enabled

    def move(self, rows, target: int) -> list[int]:
        """Move rows so they are inserted before `target` (index in current list)."""
        rows = sorted(set(self._valid(rows)))
        if not rows:
            return []
        target = max(0, min(target, len(self.actions)))
        moving = [self.actions[r] for r in rows]
        before = sum(1 for r in rows if r < target)
        new_target = target - before
        rest = [a for i, a in enumerate(self.actions) if i not in set(rows)]
        new_list = rest[:new_target] + moving + rest[new_target:]
        if [a.id for a in new_list] == [a.id for a in self.actions]:
            return rows
        self._push("Move")
        self.macro.actions = new_list
        return list(range(new_target, new_target + len(moving)))

    def move_up(self, rows):
        rows = sorted(set(self._valid(rows)))
        if not rows or rows[0] == 0:
            return rows
        return self.move(rows, rows[0] - 1)

    def move_down(self, rows):
        rows = sorted(set(self._valid(rows)))
        if not rows or rows[-1] >= len(self.actions) - 1:
            return rows
        return self.move(rows, rows[-1] + 2)

    def thin_moves(self, min_gap: float, rows=None) -> int:
        """Remove mouse-move steps closer than `min_gap` seconds to the previous
        kept move. Removed delays are added to the next step, so every other
        step keeps its exact timestamp. Returns how many steps were removed."""
        scope = set(self._valid(rows)) if rows else set(range(len(self.actions)))
        keep, carry, since_move, removed = [], 0.0, None, 0
        acts = self.actions
        for i, a in enumerate(acts):
            if a.type == "mouse_move" and i in scope:
                nxt_is_move = i + 1 < len(acts) and acts[i + 1].type == "mouse_move"
                gap = (since_move + a.delay + carry) if since_move is not None else None
                if gap is not None and gap < min_gap and nxt_is_move:
                    carry += a.delay
                    removed += 1
                    continue
                since_move = 0.0
            elif since_move is not None:
                since_move += a.delay + carry
            b = a.clone(keep_id=True)
            b.delay = round(a.delay + carry, 6)
            carry = 0.0
            keep.append(b)
        if removed:
            self._push("Thin mouse moves")
            self.macro.actions = keep
        return removed

    def mark_saved(self):
        self.dirty = False

    def _valid(self, rows):
        return [r for r in rows if 0 <= r < len(self.actions)]
