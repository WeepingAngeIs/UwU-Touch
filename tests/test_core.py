"""Tests for action timing, timeline editing, scheduling and message delivery.

Run with:  python -m pytest -q
"""
import json
import time
from datetime import datetime, timedelta

import pytest

from app.core import discord_client as dc
from app.core import schedule as sm
from app.core.hotkeys import HotkeyManager
from app.core.inputs import FakeDriver
from app.core.logbus import LogBus
from app.core.models import Action, Macro, PlaybackSettings, format_clock, parse_clock, timestamps
from app.core.player import Player
from app.core.recorder import Recorder
from app.core.scheduler import Scheduler, iso
from app.core.storage import Storage
from app.core.timeline import Timeline


def A(t, delay, **p):
    return Action(t, delay, p)


def tz():
    return datetime.now().astimezone().tzinfo


# ---------------------------------------------------------------- timing
class TestRecordingTiming:
    def test_delays_are_exact_gaps(self):
        r = Recorder(clock=lambda: 100.0)
        r.start(with_listeners=False)
        r.key_event("w", True, t=100.5)
        r.key_event("w", False, t=103.0)
        r.click_event(10, 20, "left", True, t=104.2)
        acts = r.stop()
        # a button still held at stop gets a release so playback never sticks
        assert [a.type for a in acts] == ["key_down", "key_up", "mouse_down", "mouse_up"]
        assert [round(a.delay, 3) for a in acts] == [0.5, 2.5, 1.2, 0.0]

    def test_trim_stop_button_click(self):
        r = Recorder(clock=lambda: 0.0)
        r.start(with_listeners=False)
        r.key_event("w", True, t=0.1)
        r.key_event("w", False, t=0.2)
        r.move_event(500, 500, t=0.3)           # moving to the app's Stop button
        r.click_event(500, 500, "left", True, t=0.4)
        r.click_event(500, 500, "left", False, t=0.5)
        r.click_event(1, 1, "left", False, t=0.6)  # stray release: ignored
        acts = r.stop(trim_clicks=1)
        assert [a.type for a in acts] == ["key_down", "key_up"]

    def test_pause_time_is_excluded(self):
        now = [0.0]
        r = Recorder(clock=lambda: now[0])
        r.start(with_listeners=False)
        r.key_event("a", True, t=1.0)
        now[0] = 2.0
        r.pause()
        r.key_event("b", True, t=5.0)          # ignored while paused
        now[0] = 12.0
        r.resume()                              # 10 s pause
        r.key_event("a", False, t=13.0)
        acts = r.stop()
        assert [a.params["key"] for a in acts if a.type != "key_up" or True][:2] == ["a", "a"]
        assert round(acts[1].delay, 3) == 2.0   # 1.0 -> 13.0 minus 10 s pause
        assert len([a for a in acts if a.params.get("key") == "b"]) == 0

    def test_auto_repeat_and_simultaneous_keys(self):
        r = Recorder(clock=lambda: 0.0)
        r.start(with_listeners=False)
        r.key_event("shift_l", True, t=0.1)
        r.key_event("w", True, t=0.2)
        r.key_event("w", True, t=0.25)          # auto-repeat ignored
        r.key_event("w", True, t=0.30)
        r.key_event("w", False, t=1.0)
        r.key_event("shift_l", False, t=1.1)
        acts = r.stop()
        assert [(a.type, a.params["key"]) for a in acts] == [
            ("key_down", "shift_l"), ("key_down", "w"), ("key_up", "w"), ("key_up", "shift_l")]

    def test_held_keys_released_and_hotkeys_ignored(self):
        r = Recorder(clock=lambda: 0.0, ignore_keys={"f9"})
        r.hotkey_modifiers = {"ctrl"}
        r.start(with_listeners=False)
        r.key_event("w", True, t=0.1)
        r.key_event("ctrl_l", True, t=0.5)      # part of the stop hotkey
        r.key_event("f9", True, t=0.6)
        acts = r.stop()
        keys = [(a.type, a.params["key"]) for a in acts]
        assert ("key_down", "f9") not in keys
        assert ("key_down", "ctrl_l") not in keys
        assert keys[-1] == ("key_up", "w")      # never leaves W stuck

    def test_mouse_move_throttle(self):
        r = Recorder(clock=lambda: 0.0, move_interval_ms=20)
        r.start(with_listeners=False)
        for i in range(10):
            r.move_event(i, i, t=i * 0.005)     # every 5 ms
        acts = r.stop()
        assert 2 <= len(acts) <= 3


class TestPlaybackTiming:
    def _play(self, macro, settings=None, timeout=10):
        drv = FakeDriver()
        states = []
        p = Player(lambda: drv, on_state=lambda playing, why: states.append((playing, why)))
        drv.t0 = time.perf_counter()
        p.play(macro, settings)
        p._thread.join(timeout)
        return drv, states

    def test_delays_preserved(self):
        m = Macro("t", [A("key_down", 0.0, key="w"), A("key_up", 0.3, key="w"),
                        A("mouse_down", 0.2, button="left", x=5, y=5), A("mouse_up", 0.1, button="left", x=5, y=5)])
        drv, states = self._play(m)
        keys = [e for e in drv.events if e[1] in ("key", "button")]
        times = [e[0] for e in keys]
        expected = [0.0, 0.3, 0.5, 0.6]
        for got, want in zip(times, expected):
            assert abs(got - want) < 0.03, (times, expected)
        assert states[-1] == (False, "finished")

    def test_speed_and_repeat(self):
        m = Macro("t", [A("key_down", 0.2, key="a"), A("key_up", 0.2, key="a")])
        drv, _ = self._play(m, PlaybackSettings("count", 3, loop_delay=0.1, speed=2.0))
        downs = [e[0] for e in drv.events if e[1] == "key" and e[3] is True]
        assert len(downs) == 3
        # each loop: 0.4 s / 2 = 0.2 s, plus 0.1 s loop delay -> ~0.3 s apart
        assert abs((downs[1] - downs[0]) - 0.3) < 0.04

    def test_emergency_stop_halts_and_releases(self):
        m = Macro("t", [A("key_down", 0.0, key="w"), A("key_up", 5.0, key="w"), A("key_down", 0.0, key="x")])
        drv = FakeDriver()
        states = []
        p = Player(lambda: drv, on_state=lambda playing, why: states.append(why))
        p.play(m, PlaybackSettings("forever"))
        time.sleep(0.2)
        assert drv.held_keys == {"w"}
        p.stop()
        assert not p.playing
        assert drv.held_keys == set()
        assert ("key", "w", False) in [e[1:] for e in drv.events]
        assert not any(e[1:] == ("key", "x", True) for e in drv.events)
        assert states[-1] == "stopped"

    def test_disabled_step_skipped_but_timing_kept(self):
        b = A("key_down", 0.1, key="b")
        b.enabled = False
        m = Macro("t", [A("key_down", 0.0, key="a"), b, A("key_down", 0.1, key="c")])
        drv, _ = self._play(m)
        keys = [(e[2], round(e[0], 1)) for e in drv.events if e[1] == "key" and e[3] is True]
        assert [k for k, _ in keys] == ["a", "c"]
        assert keys[-1][0] == "c" and abs(keys[-1][1] - 0.2) < 0.05

    def test_discord_step_called(self):
        sent = []
        m = Macro("t", [A("discord", 0.0, target_id=1, message="Raid starts in 10 minutes!")])
        p = Player(lambda: FakeDriver(), discord_sender=lambda params: (sent.append(params["message"]) or (True, "")))
        p.play(m)
        p._thread.join(5)
        assert sent == ["Raid starts in 10 minutes!"]


# ---------------------------------------------------------------- timeline
class TestTimeline:
    def make(self):
        acts = [A("key_down", 0.0, key="w"), A("key_up", 2.5, key="w"), A("mouse_click", 1.2, button="left", x=1, y=1),
                A("key_down", 3.0, key="space"), A("key_up", 0.15, key="space"), A("wait", 5.0)]
        return Timeline(Macro("raid", acts))

    def test_spec_example_timestamps(self):
        tl = self.make()
        assert [format_clock(t) for t in tl.times()] == ["00:00.00", "00:02.50", "00:03.70", "00:06.70", "00:06.85", "00:11.85"]

    def test_changing_delay_shifts_later_times(self):
        tl = self.make()
        tl.set_delay([1], 4.0)
        assert [round(t, 2) for t in tl.times()] == [0.0, 4.0, 5.2, 8.2, 8.35, 13.35]

    def test_set_time(self):
        tl = self.make()
        tl.set_time(3, 10.0)
        assert round(tl.actions[3].delay, 3) == 6.3
        assert round(tl.times()[4], 2) == 10.15
        with pytest.raises(ValueError):
            tl.set_time(3, 1.0)

    def test_insert_delete_undo_redo(self):
        tl = self.make()
        tl.insert(2, [A("wait", 1.0)])
        assert len(tl) == 7 and tl.actions[2].type == "wait"
        tl.delete([0, 1])
        assert len(tl) == 5
        assert tl.undo() and len(tl) == 7
        assert tl.undo() and len(tl) == 6
        assert tl.redo() and len(tl) == 7
        assert not tl.can_redo() or tl.redo()

    def test_move_duplicate_copy_paste(self):
        tl = self.make()
        ids = [a.id for a in tl.actions]
        new_rows = tl.move([0, 1], 4)
        assert [a.id for a in tl.actions] == [ids[2], ids[3], ids[0], ids[1], ids[4], ids[5]]
        assert new_rows == [2, 3]
        tl.move_up([2])
        assert tl.actions[1].id == ids[0]
        dup = tl.duplicate([0])
        assert dup == [1] and tl.actions[1].id != tl.actions[0].id and tl.actions[1].type == tl.actions[0].type
        clip = tl.copy([0, 1])
        tl.paste(len(tl), clip)
        assert len(tl) == 9

    def test_multi_select_delay_and_scale(self):
        tl = self.make()
        tl.set_delay([1, 2, 3], 0.5)
        assert [a.delay for a in tl.actions[1:4]] == [0.5, 0.5, 0.5]
        tl.scale_delays([1, 2], 2)
        assert [a.delay for a in tl.actions[1:3]] == [1.0, 1.0]
        with pytest.raises(ValueError):
            tl.set_delay([1], -1)

    def test_clock_parsing(self):
        assert parse_clock("01:02.50") == 62.5
        assert parse_clock("1:00:00") == 3600
        assert parse_clock("2.5s") == 2.5

    def test_json_roundtrip(self):
        tl = self.make()
        d = json.loads(json.dumps(tl.macro.to_dict()))
        m2 = Macro.from_dict(d)
        assert [a.to_dict() for a in m2.actions] == [a.to_dict() for a in tl.actions]
        with pytest.raises(ValueError):
            Macro.from_dict({"hello": 1})


# ---------------------------------------------------------------- schedule math
class TestScheduleMath:
    def dt(self, h, m=0, day=10):
        return datetime(2026, 11, day, h, m).astimezone()

    def test_interval(self):
        anchor = self.dt(12)
        p = {"seconds": 7200, "anchor": iso(anchor)}
        assert sm.next_run("interval", p, self.dt(12, 1)) == self.dt(14)
        assert sm.next_run("interval", p, self.dt(14)) == self.dt(16)

    def test_interval_with_start_and_end(self):
        p = {"seconds": 1800}
        start, end = self.dt(18), self.dt(19)
        times = sm.upcoming("interval", p, self.dt(9), iso(start), iso(end), count=10)
        assert times == [self.dt(18), self.dt(18, 30), self.dt(19)]

    def test_daily_and_weekdays(self):
        p = {"times": ["18:00", "9:00 PM"]}
        assert sm.next_run("daily", p, self.dt(17)) == self.dt(18)
        assert sm.next_run("daily", p, self.dt(18)) == self.dt(21)
        assert sm.next_run("daily", p, self.dt(22)) == self.dt(18, day=11)
        # 2026-11-10 is a Tuesday (1). Only Saturdays (5):
        sat = sm.next_run("daily", {"times": ["18:00"], "weekdays": [5]}, self.dt(12))
        assert sat.weekday() == 5 and sat.hour == 18

    def test_once(self):
        at = self.dt(20)
        assert sm.next_run("once", {"at": iso(at)}, self.dt(19)) == at
        assert sm.next_run("once", {"at": iso(at)}, self.dt(20)) is None

    def test_describe(self):
        assert sm.describe("interval", {"seconds": 7200}) == "Every 2 hours"
        assert sm.describe("interval", {"seconds": 45}) == "Every 45 seconds"
        assert sm.describe("daily", {"times": ["18:00"], "weekdays": [0, 1, 2, 3, 4]}) == "Weekdays at 6:00 PM"


# ---------------------------------------------------------------- scheduler + delivery
class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    s = Storage(tmp_path / "t.db")
    yield s
    s.close()


def make_sched(store, clock, sender, macro_runner=None):
    log = LogBus(store)
    return Scheduler(store, log, send_message=sender, run_macro=macro_runner or (lambda s: (True, "ok")), clock=clock)


class TestScheduler:
    def setup_msg(self, store, clock, kind="interval", params=None):
        tid = store.add_target("raid", "bot", channel_id="123456789012345678")
        sid = store.save_schedule({"job": "message", "name": "Raid", "target_id": tid, "message": "RAID!",
                                   "kind": kind, "params": params or {"seconds": 600}})
        return sid

    def test_sends_on_time_once_per_slot(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        sent = []
        sch = make_sched(store, clock, lambda s, slot: (sent.append(slot) or dc.SendResult(True)))
        sid = self.setup_msg(store, clock)
        sch.set_enabled(sid, True)
        sch.tick()
        assert sent == []
        clock.t += timedelta(minutes=10)
        sch.tick(); sch.wait_idle()
        sch.tick(); sch.wait_idle()             # same slot again -> no duplicate
        assert len(sent) == 1
        s = store.get_schedule(sid)
        assert s["last_status"] == "sent"
        assert s["next_run_at"] == iso(clock.t + timedelta(minutes=10))

    def test_no_duplicate_after_restart(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        sent = []
        sch = make_sched(store, clock, lambda s, slot: (sent.append(slot) or dc.SendResult(True)))
        sid = self.setup_msg(store, clock)
        sch.set_enabled(sid, True)
        clock.t += timedelta(minutes=10)
        slot = store.get_schedule(sid)["next_run_at"]
        # simulate a crash right after claiming the slot (before the result was saved)
        assert store.claim_slot(sid, slot)
        sch2 = make_sched(store, clock, lambda s, sl: (sent.append(sl) or dc.SendResult(True)))
        store.recover_pending()
        sch2.tick(); sch2.wait_idle()
        assert sent == []                        # uncertain slot is never re-sent
        assert store.get_schedule(sid)["next_run_at"] > slot

    def test_missed_while_closed_is_skipped_not_flooded(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        sent = []
        sch = make_sched(store, clock, lambda s, slot: (sent.append(slot) or dc.SendResult(True)))
        sid = self.setup_msg(store, clock)
        sch.set_enabled(sid, True)
        clock.t += timedelta(hours=5)            # app was closed for 5 hours
        sch.tick(); sch.wait_idle()
        assert sent == []
        assert store.get_schedule(sid)["last_status"] == "missed"
        clock.t = datetime.fromisoformat(store.get_schedule(sid)["next_run_at"])
        sch.tick(); sch.wait_idle()
        assert len(sent) == 1

    def test_retry_after_temporary_failure(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        results = [dc.SendResult(False, "no internet", retryable=True), dc.SendResult(True)]
        calls = []
        sch = make_sched(store, clock, lambda s, slot: (calls.append(slot) or results.pop(0)))
        sid = self.setup_msg(store, clock)
        sch.set_enabled(sid, True)
        clock.t += timedelta(minutes=10)
        sch.tick(); sch.wait_idle()
        assert store.get_schedule(sid)["last_status"] == "retrying"
        sch.tick(); sch.wait_idle()               # too early to retry
        assert len(calls) == 1
        clock.t += timedelta(seconds=31)
        sch.tick(); sch.wait_idle()
        assert len(calls) == 2 and calls[0] == calls[1]
        assert store.get_schedule(sid)["last_status"] == "sent"

    def test_permanent_failure_reported(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        fails = []
        sch = make_sched(store, clock, lambda s, slot: dc.SendResult(False, "403 no permission"))
        sch.on_failure = lambda title, msg: fails.append(msg)
        sid = self.setup_msg(store, clock)
        sch.set_enabled(sid, True)
        clock.t += timedelta(minutes=10)
        sch.tick(); sch.wait_idle()
        assert fails and "403" in fails[0]
        assert store.get_schedule(sid)["last_error"] == "403 no permission"

    def test_once_finishes_and_disables(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        sch = make_sched(store, clock, lambda s, slot: dc.SendResult(True))
        sid = self.setup_msg(store, clock, "once", {"at": iso(clock.t + timedelta(minutes=1))})
        sch.set_enabled(sid, True)
        clock.t += timedelta(minutes=1)
        sch.tick(); sch.wait_idle()
        s = store.get_schedule(sid)
        assert s["enabled"] == 0 and s["last_status"] == "sent"

    def test_raid_pair_example(self, store):
        """The spec's example: 'RAID IN 30 MINUTES' then 'RAID TIME' 30 minutes later."""
        clock = FakeClock(datetime(2026, 11, 10, 17, 0).astimezone())
        sent = []
        sch = make_sched(store, clock, lambda s, slot: (sent.append((s["message"], slot)) or dc.SendResult(True)))
        tid = store.add_target("guild", "webhook")
        a = store.save_schedule({"job": "message", "name": "30 min warning", "target_id": tid,
                                 "message": "⚔️ RAID IN 30 MINUTES! GET READY!", "kind": "daily", "params": {"times": ["17:30"]}})
        b = store.save_schedule({"job": "message", "name": "Raid time", "target_id": tid,
                                 "message": "🔥 RAID TIME! EVERYONE LOG IN NOW!", "kind": "daily", "params": {"times": ["18:00"]}})
        sch.set_enabled(a, True); sch.set_enabled(b, True)
        for minutes in range(0, 62):
            clock.t = datetime(2026, 11, 10, 17, 0).astimezone() + timedelta(minutes=minutes)
            sch.tick(); sch.wait_idle()
        assert [m for m, _ in sent] == ["⚔️ RAID IN 30 MINUTES! GET READY!", "🔥 RAID TIME! EVERYONE LOG IN NOW!"]

    def test_macro_schedule_paused_after_emergency(self, store):
        clock = FakeClock(datetime(2026, 11, 10, 12, 0).astimezone())
        runs = []
        sch = make_sched(store, clock, lambda s, slot: dc.SendResult(True), lambda s: (runs.append(1) or (True, "ok")))
        mid = store.save_macro(Macro("farm", [A("key_down", 0, key="a")]))
        sid = store.save_schedule({"job": "macro", "name": "farm", "macro_id": mid, "kind": "interval", "params": {"seconds": 60}})
        sch.set_enabled(sid, True)
        sch.macros_paused = True
        clock.t += timedelta(seconds=60)
        sch.tick()
        assert runs == []
        sch.macros_paused = False
        clock.t += timedelta(seconds=60)
        sch.tick()
        assert runs == [1]


# ---------------------------------------------------------------- discord client
class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []
        self.headers = {}

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, headers=None, timeout=None):
        return self.responses.pop(0)


WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abcDEF_-123"


class TestDiscordDelivery:
    def client(self, responses, per_minute=10):
        sleeps = []
        c = dc.DiscordClient(session=FakeSession(responses), flood_guard=dc.FloodGuard(per_minute), sleep=sleeps.append)
        return c, sleeps

    def test_webhook_success_and_mentions(self):
        c, _ = self.client([FakeResp(200, {"id": "999"})])
        r = c.send_webhook(WEBHOOK, "⚔️ RAID TIME GUYS!", allow_everyone=False)
        assert r.ok and r.message_id == "999"
        url, payload, _ = c.session.posts[0]
        assert url.endswith("?wait=true")
        assert "everyone" not in payload["allowed_mentions"]["parse"]

    def test_bot_uses_nonce_and_auth(self):
        c, _ = self.client([FakeResp(200, {"id": "1"})])
        r = c.send_bot("TOKEN", "123456789012345678", "hi", allow_everyone=True, nonce="abc")
        url, payload, headers = c.session.posts[0]
        assert r.ok and headers["Authorization"] == "Bot TOKEN"
        assert payload["nonce"] == "abc" and payload["enforce_nonce"] is True
        assert "everyone" in payload["allowed_mentions"]["parse"]

    def test_rate_limit_waits_and_retries(self):
        c, sleeps = self.client([FakeResp(429, {"retry_after": 1.5, "global": False}), FakeResp(200, {"id": "2"})])
        r = c.send_webhook(WEBHOOK, "hello")
        assert r.ok and sleeps and sleeps[0] >= 1.5

    def test_friendly_errors(self):
        c, _ = self.client([FakeResp(403, {"code": 50013, "message": "Missing Permissions"})])
        r = c.send_bot("T", "123456789012345678", "hi")
        assert not r.ok and "permission" in r.error.lower() and not r.retryable
        c, _ = self.client([FakeResp(404, {"message": "Unknown Webhook"})])
        assert "deleted" in c.send_webhook(WEBHOOK, "x").error

    def test_validation(self):
        c, _ = self.client([])
        assert "2000" in c.send_webhook(WEBHOOK, "x" * 2001).error
        assert "empty" in c.send_webhook(WEBHOOK, "   ").error
        assert "valid" in c.send_webhook("https://example.com/hook", "x").error
        assert "Channel ID" in c.send_bot("T", "general", "x").error

    def test_timeout_on_webhook_not_resent(self):
        import requests
        c, _ = self.client([requests.Timeout(), FakeResp(200, {"id": "x"})])
        r = c.send_webhook(WEBHOOK, "hi")
        assert not r.ok and len(c.session.posts) == 1 and "duplicates" in r.error

    def test_connection_error_retries(self):
        import requests
        c, sleeps = self.client([requests.ConnectionError(), FakeResp(200, {"id": "x"})])
        assert c.send_webhook(WEBHOOK, "hi").ok and len(sleeps) == 1

    def test_flood_guard(self):
        c, _ = self.client([FakeResp(200, {"id": str(i)}) for i in range(5)], per_minute=3)
        results = [c.send_webhook(WEBHOOK, "spam") for _ in range(5)]
        assert [r.ok for r in results] == [True, True, True, False, False]
        assert "Flood protection" in results[3].error

    def test_parsers(self):
        assert dc.parse_channel_link("https://discord.com/channels/111111111111111111/222222222222222222") == \
            ("111111111111111111", "222222222222222222")
        assert dc.parse_webhook(WEBHOOK) == ("123456789012345678", "abcDEF_-123")


def test_discord_title_parsing():
    from app.core.discord_detect import parse_title
    assert parse_title("#guild-announcements | My Guild - Discord") == ("guild-announcements", "My Guild")
    assert parse_title("(3) #raids | Guild Name - Discord") == ("raids", "Guild Name")
    assert parse_title("Discord") is None
    assert parse_title("Friends - Discord") is None


def test_hotkeys_match_with_extra_modifiers():
    hits = []
    hk = HotkeyManager()
    hk.bind("stop", "f8", lambda: hits.append("stop"), allow_injected=True)
    hk.bind("play", "ctrl+f11", lambda: hits.append("play"))
    hk.handle("shift_l", True)
    assert hk.handle("f8", True) == "stop"   # works while a macro holds Shift
    hk.handle("f8", False)
    hk.handle("shift_l", False)
    assert hk.handle("f11", True) is None    # needs Ctrl
    hk.handle("f11", False)
    hk.handle("ctrl_l", True)
    assert hk.handle("f11", True, injected=True) is None   # ignore playback's own keys
    hk.handle("f11", False)
    assert hk.handle("f11", True) == "play"
    with pytest.raises(ValueError):
        hk.bind("other", "ctrl+f11", lambda: None)
    assert hits == ["stop", "play"]


def test_storage_roundtrip(store):
    m = Macro("Raid opener", [A("key_tap", 0.5, key="1")])
    mid = store.save_macro(m)
    assert store.load_macro(mid).actions[0].params == {"key": "1"}
    with pytest.raises(ValueError):
        store.save_macro(Macro("raid OPENER"))
    store.set_setting("theme", "light")
    assert store.get_setting("theme") == "light"
    assert store.get_setting("hotkey_stop") == "f8"


def test_thin_mouse_moves_keeps_other_timestamps():
    acts = [A("mouse_move", 0.01, x=i, y=i) for i in range(10)] + [A("mouse_down", 0.5, button="left", x=9, y=9)]
    tl = Timeline(Macro("m", acts))
    before = tl.times()[-1]
    removed = tl.thin_moves(0.05)
    assert removed > 0
    assert abs(tl.times()[-1] - before) < 1e-9          # click still at the same time
    assert tl.actions[-2].params == {"x": 9, "y": 9}     # final position kept
    tl.undo()
    assert len(tl) == 11
