"""Interface tests (run without a screen). They click through the real windows."""
import os
import time

import pytest


def test_playback_timer_and_mini(win, qapp):
    rec = win.pages["recorder"]
    win.mini_auto.setChecked(True)
    rec.play()
    qapp.processEvents()
    win.mini.tick()
    assert win.mini.isVisible()
    assert not win.mini.record.isEnabled()
    first = win.engine.player.elapsed()
    time.sleep(0.15)
    rec._tick()
    win.mini.tick()
    assert win.engine.player.elapsed() > first
    assert rec.clock.text() != "00:00.00"
    win.mini.expand()
    assert not win.mini.isVisible()
    win.mini.stop()
    win.engine.player.stop(wait=2)
    end = win.engine.player.elapsed()
    time.sleep(0.05)
    assert win.engine.player.elapsed() == end

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.inputs import FakeDriver  # noqa: E402
from app.core.models import Action, Macro  # noqa: E402
from app.core.recorder import Recorder  # noqa: E402
from app.core.secrets_store import SecretStore  # noqa: E402
from app.core.storage import Storage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("NOVAMACRO_DATA", str(tmp_path))
    from app.engine import Engine
    from app.ui import common
    from app.ui.main_window import MainWindow
    monkeypatch.setattr(common, "confirm", lambda *a, **k: True)
    st = Storage(tmp_path / "t.db")
    acts = [Action("key_down", 0, {"key": "w"}), Action("key_up", 2.5, {"key": "w"}),
            Action("mouse_click", 1.2, {"button": "left", "x": 5, "y": 5}), Action("wait", 3.0, {})]
    mid = st.save_macro(Macro("Raid", acts))
    st.set_setting("last_macro_id", mid)
    st.set_setting("countdown_seconds", 0)
    st.set_setting("minimize_while_active", False)
    e = Engine(st, SecretStore(tmp_path / "s.json", use_keyring=False), start_threads=False)
    e.player.driver_factory = FakeDriver
    w = MainWindow(e)
    w.show()
    qapp.processEvents()
    yield w
    w._shutdown()
    w._really_quit = True
    w.hide()
    w.deleteLater()
    qapp.processEvents()
    st.close()


def pump(qapp, secs=0.05):
    end = time.time() + secs
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_editing_delay_in_table_recalculates_times(win, qapp):
    tlp = win.pages["timeline"]
    idx = tlp.model.index(1, 5)
    assert tlp.model.setData(idx, 4.0, Qt.EditRole)
    assert [round(t, 2) for t in win.session.timeline.times()] == [0.0, 4.0, 5.2, 8.2]
    assert tlp.model.data(tlp.model.index(3, 6)) == "00:08.20"


def test_dashboard_action_editor_applies(win, qapp):
    dash = win.pages["dashboard"]
    win.pages["timeline"]._select([2])
    qapp.processEvents()
    assert dash._editing_row == 2
    dash.editor.delay.setValue(0.5)
    dash.editor.count.setValue(2)
    dash._apply_edit()
    a = win.session.timeline.actions[2]
    assert a.delay == 0.5 and a.params["count"] == 2
    assert win.session.dirty


def test_drag_drop_reorder_and_undo(win, qapp):
    tlp = win.pages["timeline"]
    first = win.session.timeline.actions[0].id
    tlp.view.rows_dropped.emit([0], 3)
    assert win.session.timeline.actions[2].id == first
    tlp.undo()
    assert win.session.timeline.actions[0].id == first


def test_playback_options_stay_in_sync(win, qapp):
    dash, rec = win.pages["dashboard"], win.pages["recorder"]
    dash.loop2.setChecked(True)
    assert win.session.macro.playback.repeat_mode == "forever"
    assert rec.r_forever.isChecked() and dash.loop_cb.isChecked()
    dash.loop2.setChecked(False)
    rec.repeat_n.setValue(3)
    rec.r_count.setChecked(True)
    assert dash.repeat.value() == 3 and dash.repeat2.value() == 3


def test_record_append_flow(win, qapp):
    rec = win.pages["recorder"]
    e = win.engine
    r = Recorder(clock=lambda: 0.0)
    r.start(with_listeners=False)
    e.recorder = r
    rec._mode = "append"
    r.key_event("space", True, t=0.5)
    r.key_event("space", False, t=0.6)
    rec.stop_record("hotkey")
    acts = win.session.timeline.actions
    assert len(acts) == 6 and acts[-1].params["key"] == "space"


def test_play_and_emergency_stop(win, qapp):
    rec = win.pages["recorder"]
    win.session.macro.actions = [Action("key_down", 0, {"key": "w"}), Action("key_up", 5, {"key": "w"})]
    rec.r_once.setChecked(True)
    rec.play()
    pump(qapp, 0.2)
    assert win.engine.player.playing
    win.emergency_stop()
    pump(qapp, 0.1)
    assert not win.engine.player.playing
    assert "Not playing" in win.pill_play.text()


def test_schedule_toggle_from_scheduler(win, qapp):
    st = win.storage
    tid = st.add_target("#raids", "webhook")
    st.update_target(tid, last_test_ok=1)
    sid = st.save_schedule({"job": "message", "name": "Raid", "target_id": tid, "message": "RAID!",
                            "kind": "daily", "params": {"times": ["18:00"]}})
    page = win.pages["scheduler"]
    page.refresh()
    page._set_enabled(sid, True)
    s = st.get_schedule(sid)
    assert s["enabled"] == 1 and s["next_run_at"]
    win.pages["dashboard"].refresh_schedules()
    assert win.pages["dashboard"].sched.rowCount() == 1


def test_every_tab_opens(win, qapp):
    from app.ui.main_window import PAGES
    for key, _ in PAGES:
        win.go(key)
        qapp.processEvents()
    win.apply_theme("light")
    win.apply_theme("dark")
