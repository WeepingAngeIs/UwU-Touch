"""Pure schedule math: when should something run next?

Schedule kinds
  interval: params {"seconds": N, "anchor": iso}  -> every N seconds
  daily:    params {"times": ["18:00", "21:00"], "weekdays": [0..6]} (Mon=0; empty = every day)
  once:     params {"at": iso}
Optional start_at / end_at limit the window. "Until stopped" = no end.
"""
from __future__ import annotations

import math
from datetime import datetime, time as dtime, timedelta

from .storage import parse_dt

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRESETS = [
    ("Every 5 minutes", 300), ("Every 10 minutes", 600), ("Every 15 minutes", 900),
    ("Every 30 minutes", 1800), ("Every 1 hour", 3600), ("Every 2 hours", 7200),
    ("Every 3 hours", 10800), ("Every 6 hours", 21600), ("Every 12 hours", 43200),
    ("Every 24 hours", 86400),
]


def parse_hhmm(text: str) -> dtime:
    text = text.strip().upper().replace(".", ":")
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a time. Use 18:00 or 6:00 PM.")


def _local(d, t: dtime) -> datetime:
    return datetime.combine(d, t).astimezone()  # naive local -> aware local (handles DST)


def next_run(kind: str, params: dict, after: datetime, start_at=None, end_at=None):
    """Earliest run time strictly after `after` (aware datetime), or None."""
    start = parse_dt(start_at) if isinstance(start_at, str) else start_at
    end = parse_dt(end_at) if isinstance(end_at, str) else end_at
    if start and after < start:
        floor = start - timedelta(microseconds=1)  # the start time itself may run
    else:
        floor = after
    result = None

    if kind == "interval":
        seconds = float(params.get("seconds", 0))
        if seconds <= 0:
            raise ValueError("Interval must be more than 0 seconds")
        anchor = start or parse_dt(params.get("anchor")) or after
        if floor < anchor:
            result = anchor
        else:
            k = math.floor((floor - anchor).total_seconds() / seconds) + 1
            result = anchor + timedelta(seconds=k * seconds)
            if result <= floor:  # float rounding guard
                result += timedelta(seconds=seconds)
    elif kind == "daily":
        times = sorted(parse_hhmm(t) for t in params.get("times") or [])
        if not times:
            raise ValueError("Add at least one time of day")
        days = set(params.get("weekdays") or range(7))
        d = floor.date()
        for _ in range(9):
            if d.weekday() in days:
                for t in times:
                    cand = _local(d, t)
                    if cand > floor:
                        result = cand
                        break
            if result:
                break
            d += timedelta(days=1)
    elif kind == "once":
        at = parse_dt(params.get("at"))
        if at is None:
            raise ValueError("Pick a date and time")
        result = at if at > floor else None
    else:
        raise ValueError(f"Unknown schedule type {kind}")

    if result is not None and end is not None and result > end:
        return None
    return result


def upcoming(kind, params, after, start_at=None, end_at=None, count=5):
    out = []
    t = after
    for _ in range(count):
        t = next_run(kind, params, t, start_at, end_at)
        if t is None:
            break
        out.append(t)
    return out


def describe(kind: str, params: dict, start_at=None, end_at=None) -> str:
    if kind == "interval":
        s = float(params.get("seconds", 0))
        for label, secs in PRESETS:
            if secs == s:
                text = label
                break
        else:
            text = f"Every {human_seconds(s)}"
    elif kind == "daily":
        times = ", ".join(_fmt_time(parse_hhmm(t)) for t in params.get("times") or [])
        days = params.get("weekdays") or []
        if not days or len(days) == 7:
            text = f"Every day at {times}"
        elif sorted(days) == [0, 1, 2, 3, 4]:
            text = f"Weekdays at {times}"
        elif sorted(days) == [5, 6]:
            text = f"Weekends at {times}"
        else:
            text = f"{', '.join(WEEKDAY_NAMES[d] for d in sorted(days))} at {times}"
    elif kind == "once":
        at = parse_dt(params.get("at"))
        text = f"Once on {fmt_dt(at)}" if at else "Once"
    else:
        text = kind
    if start_at:
        text += f", from {fmt_dt(parse_dt(start_at) if isinstance(start_at, str) else start_at)}"
    if end_at:
        text += f", until {fmt_dt(parse_dt(end_at) if isinstance(end_at, str) else end_at)}"
    return text


def human_seconds(s: float) -> str:
    s = int(round(s))
    if s % 3600 == 0:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''}"
    if s % 60 == 0:
        m = s // 60
        return f"{m} minute{'s' if m != 1 else ''}"
    return f"{s} second{'s' if s != 1 else ''}"


def _fmt_time(t: dtime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    now = datetime.now().astimezone()
    t = dt.strftime("%I:%M:%S %p").lstrip("0") if dt.second else dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == now.date():
        return f"Today {t}"
    if dt.date() == (now + timedelta(days=1)).date():
        return f"Tomorrow {t}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {t}"
    return f"{dt.strftime('%a %b')} {dt.day}, {t}"
