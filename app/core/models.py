"""Data models: macro actions and macros."""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from . import keynames

ACTION_TYPES = {
    "key_down": "Press key",
    "key_up": "Release key",
    "key_tap": "Tap key (press + release)",
    "mouse_move": "Move mouse",
    "mouse_down": "Mouse button down",
    "mouse_up": "Mouse button up",
    "mouse_click": "Mouse click",
    "scroll": "Scroll wheel",
    "wait": "Wait",
    "type_text": "Type text",
    "discord": "Send Discord message",
}

BUTTON_NAMES = {"left": "Left", "right": "Right", "middle": "Middle", "x1": "Back (X1)", "x2": "Forward (X2)"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Action:
    type: str
    delay: float = 0.0  # seconds to wait BEFORE this action
    params: dict = field(default_factory=dict)
    enabled: bool = True
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "delay": round(self.delay, 6),
                "params": self.params, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        if d.get("type") not in ACTION_TYPES:
            raise ValueError(f"Unknown action type: {d.get('type')}")
        delay = float(d.get("delay", 0.0))
        if delay < 0:
            raise ValueError("Delay cannot be negative")
        return cls(type=d["type"], delay=delay, params=dict(d.get("params") or {}),
                   enabled=bool(d.get("enabled", True)), id=d.get("id") or new_id())

    def clone(self, keep_id: bool = False) -> "Action":
        a = Action(self.type, self.delay, copy.deepcopy(self.params), self.enabled)
        if keep_id:
            a.id = self.id
        return a

    def title(self) -> str:
        """Short action name for the timeline's Action column."""
        return {"key_down": "Key Press", "key_up": "Key Release", "key_tap": "Key Tap", "mouse_move": "Mouse Move",
                "mouse_down": "Mouse Down", "mouse_up": "Mouse Up", "mouse_click": "Mouse Click",
                "scroll": "Scroll", "wait": "Wait", "type_text": "Type Text", "discord": "Discord Message"}.get(self.type, self.type)

    def details(self) -> str:
        """Details column text, e.g. 'W (press)', 'Left Click at (10, 20)'."""
        p, t = self.params, self.type
        if t in ("key_down", "key_up", "key_tap"):
            verb = {"key_down": "press", "key_up": "release", "key_tap": "tap"}[t]
            return f"{keynames.pretty(p.get('key', '?'))} ({verb})"
        if t == "mouse_move":
            return f"Move to ({p.get('x')}, {p.get('y')})"
        if t in ("mouse_down", "mouse_up", "mouse_click"):
            n = int(p.get("count", 1))
            kind = "Click" if t == "mouse_click" and n == 1 else "Double Click" if t == "mouse_click" and n == 2 else \
                f"{n}x Click" if t == "mouse_click" else ("down" if t == "mouse_down" else "up")
            b = BUTTON_NAMES.get(p.get("button"), str(p.get("button"))).split(" ")[0]
            return f"{b} {kind} at ({p.get('x')}, {p.get('y')})"
        if t == "wait":
            return f"Wait for {self.delay:.2f} seconds" + (f" — {p['note']}" if p.get("note") else "")
        if t == "discord":
            msg = p.get("message", "").replace("\n", " ")
            return f'"{msg[:45]}{"…" if len(msg) > 45 else ""}"' + (f"  → {p['target_name']}" if p.get("target_name") else "")
        return self.describe().split(" ", 1)[-1] if t == "scroll" else self.describe()

    def describe(self) -> str:
        p = self.params
        t = self.type
        if t == "key_down":
            return f"Press {keynames.pretty(p.get('key', '?'))}"
        if t == "key_up":
            return f"Release {keynames.pretty(p.get('key', '?'))}"
        if t == "key_tap":
            return f"Tap {keynames.pretty(p.get('key', '?'))}"
        if t == "mouse_move":
            return f"Move mouse to ({p.get('x')}, {p.get('y')})"
        if t in ("mouse_down", "mouse_up"):
            verb = "down" if t == "mouse_down" else "up"
            return f"{BUTTON_NAMES.get(p.get('button'), p.get('button'))} mouse {verb} at ({p.get('x')}, {p.get('y')})"
        if t == "mouse_click":
            n = int(p.get("count", 1))
            kind = {1: "click", 2: "double-click", 3: "triple-click"}.get(n, f"{n}x click")
            return f"{BUTTON_NAMES.get(p.get('button'), p.get('button'))} {kind} at ({p.get('x')}, {p.get('y')})"
        if t == "scroll":
            dy, dx = int(p.get("dy", 0)), int(p.get("dx", 0))
            parts = []
            if dy:
                parts.append(f"{'up' if dy > 0 else 'down'} {abs(dy)}")
            if dx:
                parts.append(f"{'right' if dx > 0 else 'left'} {abs(dx)}")
            return "Scroll " + (", ".join(parts) or "0")
        if t == "wait":
            return f"Wait (custom pause) {p.get('note', '')}".strip()
        if t == "type_text":
            text = p.get("text", "")
            return f'Type "{text[:40]}{"…" if len(text) > 40 else ""}"'
        if t == "discord":
            msg = p.get("message", "")
            target = p.get("target_name") or f"channel #{p.get('target_id')}"
            return f'Discord → {target}: "{msg[:40]}{"…" if len(msg) > 40 else ""}"'
        return t


@dataclass
class PlaybackSettings:
    repeat_mode: str = "once"  # once | count | forever
    repeat_count: int = 1
    loop_delay: float = 0.0
    speed: float = 1.0

    def to_dict(self):
        return {"repeat_mode": self.repeat_mode, "repeat_count": self.repeat_count,
                "loop_delay": self.loop_delay, "speed": self.speed}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        s = cls(d.get("repeat_mode", "once"), int(d.get("repeat_count", 1)),
                float(d.get("loop_delay", 0.0)), float(d.get("speed", 1.0)))
        if s.repeat_mode not in ("once", "count", "forever"):
            s.repeat_mode = "once"
        s.repeat_count = max(1, s.repeat_count)
        s.loop_delay = max(0.0, s.loop_delay)
        s.speed = min(max(s.speed, 0.05), 20.0)
        return s


@dataclass
class Macro:
    name: str
    actions: list = field(default_factory=list)
    playback: PlaybackSettings = field(default_factory=PlaybackSettings)
    id: int | None = None  # database row id

    FORMAT = "novamacrohub.macro"
    VERSION = 1

    def to_dict(self) -> dict:
        return {"format": self.FORMAT, "version": self.VERSION, "name": self.name,
                "playback": self.playback.to_dict(),
                "actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, d: dict) -> "Macro":
        if not isinstance(d, dict) or "actions" not in d:
            raise ValueError("This file is not a macro profile (no 'actions' list).")
        name = str(d.get("name") or "Imported macro").strip() or "Imported macro"
        return cls(name=name, actions=[Action.from_dict(a) for a in d["actions"]],
                   playback=PlaybackSettings.from_dict(d.get("playback")))

    def total_duration(self) -> float:
        return sum(a.delay for a in self.actions)


def timestamps(actions) -> list[float]:
    """Elapsed time at which each action fires (cumulative delays)."""
    out, t = [], 0.0
    for a in actions:
        t += a.delay
        out.append(t)
    return out


def format_clock(seconds: float) -> str:
    """12.345 -> '00:12.35'; 3725.5 -> '1:02:05.50'."""
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    s = (total_cs // 100) % 60
    m = (total_cs // 6000) % 60
    h = total_cs // 360000
    if h:
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    return f"{m:02d}:{s:02d}.{cs:02d}"


def parse_clock(text: str) -> float:
    """Inverse of format_clock. Accepts '12.5', '01:02.30', '1:02:03.5'."""
    text = text.strip().lower().rstrip("s")
    if not text:
        raise ValueError("Empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("Use mm:ss.cc or h:mm:ss.cc")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError("Time cannot be negative")
    return total
