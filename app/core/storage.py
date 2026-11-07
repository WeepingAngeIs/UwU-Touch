"""SQLite storage for macros, Discord channels, schedules, logs and settings."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

from .models import Macro

SCHEMA = """
CREATE TABLE IF NOT EXISTS macros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discord_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 'webhook' or 'bot'
    channel_id TEXT,
    guild_id TEXT,
    channel_name TEXT,
    guild_name TEXT,
    last_test_ok INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,               -- 'message' or 'macro'
    name TEXT NOT NULL,
    target_id INTEGER,               -- discord_targets.id for messages
    macro_id INTEGER,                -- macros.id for macro runs
    message TEXT,
    allow_everyone INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 0,
    kind TEXT NOT NULL,              -- 'interval' | 'daily' | 'once'
    params TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    last_run_at TEXT,
    next_run_at TEXT,
    last_status TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL,            -- 'pending' | 'sent' | 'failed' | 'missed' | 'skipped'
    updated_at TEXT NOT NULL,
    error TEXT,
    UNIQUE(schedule_id, slot)
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    category TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "theme": "dark",
    "hotkey_record": "f9",
    "hotkey_pause": "f10",
    "hotkey_play": "f11",
    "hotkey_stop": "f8",
    "record_mouse_moves": True,
    "mouse_move_interval_ms": 15,
    "input_mode": "scancode",          # scancode (games) | virtualkey
    "default_speed": 1.0,
    "catchup_minutes": 5,
    "min_interval_seconds": 10,
    "flood_per_minute": 10,
    "minimize_to_tray": True,
    "start_minimized": False,
    "start_with_windows": False,
    "last_macro_id": None,
    "countdown_seconds": 3,
}


def data_dir() -> Path:
    base = os.environ.get("NOVAMACRO_DATA")
    if base:
        p = Path(base)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home())) / "NovaMacroHub"
    else:
        p = Path.home() / ".novamacrohub"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_dt(text):
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


class Storage:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or (data_dir() / "novamacrohub.db"))
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def _exec(self, sql, args=()):
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        with self._lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    # ---- settings -----------------------------------------------------
    def get_setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return DEFAULT_SETTINGS.get(key, default) if default is None else default
        return json.loads(row["value"])

    def set_setting(self, key, value):
        self._exec("INSERT INTO settings(key,value) VALUES(?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def all_settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        for r in self._all("SELECT key,value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    # ---- macros -------------------------------------------------------
    def list_macros(self):
        rows = self._all("SELECT id,name,data,updated_at FROM macros ORDER BY name COLLATE NOCASE")
        out = []
        for r in rows:
            d = json.loads(r["data"])
            acts = d.get("actions", [])
            out.append({"id": r["id"], "name": r["name"], "updated_at": r["updated_at"],
                        "steps": len(acts), "duration": sum(float(a.get("delay", 0)) for a in acts)})
        return out

    def load_macro(self, macro_id: int) -> Macro | None:
        r = self._one("SELECT id,name,data FROM macros WHERE id=?", (macro_id,))
        if not r:
            return None
        m = Macro.from_dict(json.loads(r["data"]))
        m.id, m.name = r["id"], r["name"]
        return m

    def save_macro(self, macro: Macro) -> int:
        name = macro.name.strip()
        if not name:
            raise ValueError("Macro needs a name")
        clash = self._one("SELECT id FROM macros WHERE name=? COLLATE NOCASE", (name,))
        if clash and clash["id"] != macro.id:
            raise ValueError(f"Another macro is already called '{name}'")
        data = json.dumps(macro.to_dict())
        if macro.id is None:
            cur = self._exec("INSERT INTO macros(name,data,updated_at) VALUES(?,?,?)", (name, data, now_iso()))
            macro.id = cur.lastrowid
        else:
            self._exec("UPDATE macros SET name=?,data=?,updated_at=? WHERE id=?", (name, data, now_iso(), macro.id))
        return macro.id

    def delete_macro(self, macro_id: int):
        self._exec("DELETE FROM schedules WHERE job='macro' AND macro_id=?", (macro_id,))
        self._exec("DELETE FROM macros WHERE id=?", (macro_id,))

    def unique_macro_name(self, base: str) -> str:
        names = {m["name"].lower() for m in self.list_macros()}
        if base.lower() not in names:
            return base
        i = 2
        while f"{base} ({i})".lower() in names:
            i += 1
        return f"{base} ({i})"

    # ---- discord targets ----------------------------------------------
    def list_targets(self):
        return self._all("SELECT * FROM discord_targets ORDER BY name COLLATE NOCASE")

    def get_target(self, target_id):
        return self._one("SELECT * FROM discord_targets WHERE id=?", (target_id,))

    def add_target(self, name, kind, channel_id=None, guild_id=None, channel_name=None, guild_name=None) -> int:
        cur = self._exec("INSERT INTO discord_targets(name,kind,channel_id,guild_id,channel_name,guild_name,created_at)"
                         " VALUES(?,?,?,?,?,?,?)", (name, kind, channel_id, guild_id, channel_name, guild_name, now_iso()))
        return cur.lastrowid

    def update_target(self, target_id, **fields):
        allowed = {"name", "channel_id", "guild_id", "channel_name", "guild_name", "last_test_ok"}
        sets = [(k, v) for k, v in fields.items() if k in allowed]
        if not sets:
            return
        self._exec(f"UPDATE discord_targets SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                   tuple(v for _, v in sets) + (target_id,))

    def delete_target(self, target_id):
        self._exec("UPDATE schedules SET enabled=0, target_id=NULL WHERE target_id=?", (target_id,))
        self._exec("DELETE FROM discord_targets WHERE id=?", (target_id,))

    # ---- schedules ----------------------------------------------------
    def list_schedules(self, job=None):
        if job:
            rows = self._all("SELECT * FROM schedules WHERE job=? ORDER BY name COLLATE NOCASE", (job,))
        else:
            rows = self._all("SELECT * FROM schedules ORDER BY name COLLATE NOCASE")
        for r in rows:
            r["params"] = json.loads(r["params"])
        return rows

    def get_schedule(self, sid):
        r = self._one("SELECT * FROM schedules WHERE id=?", (sid,))
        if r:
            r["params"] = json.loads(r["params"])
        return r

    def save_schedule(self, s: dict) -> int:
        cols = ["job", "name", "target_id", "macro_id", "message", "allow_everyone", "enabled",
                "kind", "params", "start_at", "end_at", "next_run_at", "last_run_at", "last_status", "last_error"]
        vals = dict(s)
        vals["params"] = json.dumps(s.get("params") or {})
        vals.setdefault("allow_everyone", 0)
        vals.setdefault("enabled", 0)
        if s.get("id"):
            present = [c for c in cols if c in vals]
            self._exec(f"UPDATE schedules SET {', '.join(c + '=?' for c in present)} WHERE id=?",
                       tuple(vals[c] for c in present) + (s["id"],))
            return s["id"]
        present = [c for c in cols if c in vals]
        cur = self._exec(f"INSERT INTO schedules({', '.join(present)}, created_at) VALUES({', '.join('?' * len(present))}, ?)",
                         tuple(vals[c] for c in present) + (now_iso(),))
        return cur.lastrowid

    def update_schedule(self, sid, **fields):
        if "params" in fields:
            fields["params"] = json.dumps(fields["params"])
        if not fields:
            return
        self._exec(f"UPDATE schedules SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                   tuple(fields.values()) + (sid,))

    def delete_schedule(self, sid):
        self._exec("DELETE FROM send_log WHERE schedule_id=?", (sid,))
        self._exec("DELETE FROM schedules WHERE id=?", (sid,))

    # ---- send log (duplicate protection) ------------------------------
    def claim_slot(self, schedule_id, slot: str) -> bool:
        """Reserve a send slot. Returns False if this slot was already handled
        (sent, missed, or in an unknown state after a crash)."""
        with self._lock:
            row = self.conn.execute("SELECT status FROM send_log WHERE schedule_id=? AND slot=?",
                                    (schedule_id, slot)).fetchone()
            if row is not None:
                if row["status"] == "retry":
                    self.conn.execute("UPDATE send_log SET status='pending', updated_at=? WHERE schedule_id=? AND slot=?",
                                      (now_iso(), schedule_id, slot))
                    self.conn.commit()
                    return True
                return False
            self.conn.execute("INSERT INTO send_log(schedule_id,slot,status,updated_at) VALUES(?,?, 'pending', ?)",
                              (schedule_id, slot, now_iso()))
            self.conn.commit()
            return True

    def finish_slot(self, schedule_id, slot: str, status: str, error: str | None = None):
        self._exec("INSERT INTO send_log(schedule_id,slot,status,updated_at,error) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(schedule_id,slot) DO UPDATE SET status=excluded.status, "
                   "updated_at=excluded.updated_at, error=excluded.error",
                   (schedule_id, slot, status, now_iso(), error))

    def slot_status(self, schedule_id, slot):
        r = self._one("SELECT status FROM send_log WHERE schedule_id=? AND slot=?", (schedule_id, slot))
        return r["status"] if r else None

    def recover_pending(self):
        """After a crash, 'pending' rows are uncertain. Mark them so they are never resent."""
        self._exec("UPDATE send_log SET status='uncertain' WHERE status='pending'")

    # ---- activity log -------------------------------------------------
    def add_log(self, category, level, message, ts=None):
        self._exec("INSERT INTO activity_log(ts,category,level,message) VALUES(?,?,?,?)",
                   (ts or now_iso(), category, level, message))

    def list_logs(self, limit=2000, category=None, search=None):
        sql = "SELECT * FROM activity_log WHERE 1=1"
        args = []
        if category and category != "All":
            if category == "Errors":
                sql += " AND level='error'"
            else:
                sql += " AND category=?"
                args.append(category)
        if search:
            sql += " AND message LIKE ?"
            args.append(f"%{search}%")
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return self._all(sql, args)

    def clear_logs(self):
        self._exec("DELETE FROM activity_log")

    def trim_logs(self, keep=20000):
        self._exec("DELETE FROM activity_log WHERE id <= (SELECT MAX(id) FROM activity_log) - ?", (keep,))
