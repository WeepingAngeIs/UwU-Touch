"""Background scheduler for Discord messages and timed macro runs.

Runs on its own thread, independent of the recorder and player. Duplicate
protection: every send is tied to a (schedule, time-slot) row in the database
that is claimed before sending. A slot that was already handled is never sent
again, including after a crash or restart. Slots that were missed while the app
was closed (older than the catch-up window) are logged and skipped instead of
flooding the channel when the app starts again.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable

from . import schedule as sched_math
from .storage import Storage, parse_dt

RETRY_SECONDS = 30


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def local_now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


class Scheduler:
    def __init__(self, storage: Storage, log, send_message: Callable, run_macro: Callable,
                 on_change: Callable | None = None, on_failure: Callable | None = None,
                 clock: Callable = local_now, workers: int = 4):
        self.storage = storage
        self.log = log
        self.send_message = send_message      # fn(schedule_row, slot_iso) -> SendResult
        self.run_macro = run_macro            # fn(schedule_row) -> (ok, message)
        self.on_change = on_change or (lambda: None)
        self.on_failure = on_failure or (lambda title, msg: None)
        self.clock = clock
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="discord-send")
        self._inflight: set[int] = set()
        self._retry_at: dict[int, datetime] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.messages_paused = False
        self.macros_paused = False   # set by emergency stop until the user resumes

    # ---- lifecycle ----------------------------------------------------
    def start(self):
        self.storage.recover_pending()
        now = self.clock()
        for s in self.storage.list_schedules():
            if s["enabled"] and not s["next_run_at"]:
                self._recompute(s, now)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def shutdown(self):
        self._stop.set()
        if self._thread:
            self._thread.join(3)
        self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def _loop(self):
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception as e:  # never let the scheduler thread die
                self.log.error("Scheduler", f"Scheduler error: {e}")

    # ---- user operations ----------------------------------------------
    def catchup(self) -> timedelta:
        return timedelta(minutes=float(self.storage.get_setting("catchup_minutes") or 5))

    def set_enabled(self, sid: int, enabled: bool):
        s = self.storage.get_schedule(sid)
        if not s:
            return
        if enabled:
            now = self.clock()
            if s["kind"] == "interval" and not s["start_at"]:
                params = dict(s["params"])
                params["anchor"] = iso(now)  # "every N" counts from the moment it is switched on
                s["params"] = params
                self.storage.update_schedule(sid, params=params)
            s["enabled"] = 1
            nxt = self._recompute(s, now)
            if nxt is None:
                self.storage.update_schedule(sid, enabled=0)
                raise ValueError("This schedule has no future send times (check the date, end date or times).")
            self.storage.update_schedule(sid, enabled=1, last_status="waiting", last_error=None)
            self.log.info("Scheduler", f"Enabled '{s['name']}'. Next: {sched_math.fmt_dt(nxt)}")
        else:
            self.storage.update_schedule(sid, enabled=0, next_run_at=None, last_status="off")
            self._retry_at.pop(sid, None)
            self.log.info("Scheduler", f"Disabled '{s['name']}'.")
        self.on_change()

    def refresh(self, sid: int):
        """Recalculate the next run after a schedule was edited."""
        s = self.storage.get_schedule(sid)
        if s and s["enabled"]:
            if self._recompute(s, self.clock()) is None:
                self.storage.update_schedule(sid, enabled=0, last_status="finished")
        self.on_change()

    def skip_next(self, sid: int):
        s = self.storage.get_schedule(sid)
        if not s or not s["enabled"] or not s["next_run_at"]:
            return
        slot = parse_dt(s["next_run_at"])
        self.storage.finish_slot(sid, s["next_run_at"], "skipped")
        nxt = sched_math.next_run(s["kind"], s["params"], slot, s["start_at"], s["end_at"])
        self.storage.update_schedule(sid, next_run_at=iso(nxt) if nxt else None,
                                     enabled=1 if nxt else 0, last_status="waiting" if nxt else "finished")
        self.log.info("Scheduler", f"Skipped one send of '{s['name']}'.")
        self.on_change()

    def _recompute(self, s, now):
        nxt = sched_math.next_run(s["kind"], s["params"], now, s["start_at"], s["end_at"])
        self.storage.update_schedule(s["id"], next_run_at=iso(nxt) if nxt else None)
        return nxt

    # ---- the tick -----------------------------------------------------
    def tick(self, now: datetime | None = None):
        now = now or self.clock()
        changed = False
        for s in self.storage.list_schedules():
            if not s["enabled"] or not s["next_run_at"]:
                continue
            sid = s["id"]
            with self._lock:
                if sid in self._inflight:
                    continue
            retry = self._retry_at.get(sid)
            if retry and retry > now:
                continue
            slot_dt = parse_dt(s["next_run_at"])
            if slot_dt > now:
                continue
            if s["job"] == "message" and self.messages_paused:
                continue
            changed = True
            if now - slot_dt > self.catchup():
                self._missed(s, slot_dt, now)
                continue
            if s["job"] == "macro":
                self._run_macro(s, slot_dt, now)
            else:
                self._dispatch_message(s, slot_dt, now)
        if changed:
            self.on_change()

    def _advance(self, s, slot_dt, now, **extra):
        nxt = sched_math.next_run(s["kind"], s["params"], max(slot_dt, now), s["start_at"], s["end_at"])
        fields = dict(next_run_at=iso(nxt) if nxt else None, **extra)
        if nxt is None:
            fields["enabled"] = 0
            fields.setdefault("last_status", "finished")
        self.storage.update_schedule(s["id"], **fields)
        self._retry_at.pop(s["id"], None)

    def _missed(self, s, slot_dt, now):
        self.storage.finish_slot(s["id"], iso(slot_dt), "missed")
        self.log.warn("Scheduler", f"Skipped '{s['name']}' planned for {sched_math.fmt_dt(slot_dt)} — "
                                   "the app was closed, asleep or paused at that time.")
        self._advance(s, slot_dt, now, last_status="missed")

    def _run_macro(self, s, slot_dt, now):
        slot = iso(slot_dt)
        if not self.storage.claim_slot(s["id"], slot):
            self._advance(s, slot_dt, now)
            return
        if self.macros_paused:
            self.storage.finish_slot(s["id"], slot, "skipped", "Emergency stop is active")
            self.log.warn("Scheduler", f"Did not run macro '{s['name']}': macro schedules are paused "
                                       "after Emergency Stop (press 'Resume macro schedules').")
            self._advance(s, slot_dt, now, last_status="skipped")
            return
        try:
            ok, msg = self.run_macro(s)
        except Exception as e:
            ok, msg = False, str(e)
        self.storage.finish_slot(s["id"], slot, "sent" if ok else "failed", None if ok else msg)
        if ok:
            self.log.info("Scheduler", f"Started scheduled macro '{s['name']}'.")
            self._advance(s, slot_dt, now, last_run_at=iso(now), last_status="ran", last_error=None)
        else:
            self.log.error("Scheduler", f"Scheduled macro '{s['name']}' did not run: {msg}")
            self.on_failure("Scheduled macro did not run", f"{s['name']}: {msg}")
            self._advance(s, slot_dt, now, last_status="failed", last_error=msg)

    def _dispatch_message(self, s, slot_dt, now):
        slot = iso(slot_dt)
        if not self.storage.claim_slot(s["id"], slot):
            status = self.storage.slot_status(s["id"], slot)
            if status in ("uncertain",):
                self.log.warn("Discord", f"'{s['name']}' at {sched_math.fmt_dt(slot_dt)} was interrupted by a "
                                         "restart and may already have been sent; not sending again.")
            self._advance(s, slot_dt, now)
            return
        with self._lock:
            self._inflight.add(s["id"])
        self.storage.update_schedule(s["id"], last_status="sending")
        self._pool.submit(self._send_job, s, slot_dt, slot)

    def _send_job(self, s, slot_dt, slot):
        try:
            try:
                res = self.send_message(s, slot)
            except Exception as e:
                from .discord_client import SendResult
                res = SendResult(False, str(e))
            now = self.clock()
            if res.ok:
                self.storage.finish_slot(s["id"], slot, "sent")
                self.log.info("Discord", f"Sent '{s['name']}'.")
                self._advance(s, slot_dt, now, last_run_at=iso(now), last_status="sent", last_error=None)
            elif res.retryable and now - slot_dt + timedelta(seconds=RETRY_SECONDS) <= self.catchup():
                self.storage.finish_slot(s["id"], slot, "retry", res.error)
                self._retry_at[s["id"]] = now + timedelta(seconds=RETRY_SECONDS)
                self.storage.update_schedule(s["id"], last_status="retrying", last_error=res.error)
                self.log.warn("Discord", f"'{s['name']}' failed, will retry in {RETRY_SECONDS}s: {res.error}")
            else:
                self.storage.finish_slot(s["id"], slot, "failed", res.error)
                self.log.error("Discord", f"'{s['name']}' was not sent: {res.error}")
                self.on_failure("Discord message failed", f"{s['name']}: {res.error}")
                self._advance(s, slot_dt, now, last_status="failed", last_error=res.error)
        finally:
            with self._lock:
                self._inflight.discard(s["id"])
            self.on_change()

    def wait_idle(self, timeout=5.0):
        """Test helper: wait until no sends are in flight."""
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if not self._inflight:
                    return True
            time.sleep(0.01)
        return False
