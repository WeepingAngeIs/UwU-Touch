"""Main window: sidebar navigation, status indicators, emergency stop and tray icon."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QApplication, QCheckBox, QButtonGroup, QFrame, QPushButton, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from datetime import datetime

from ..core import keynames
from .common import CURRENT_THEME, Backdrop, CatLogo, app_icon, button, confirm, muted, set_pill, tray_icon
from .page_discord import DiscordPage
from .page_dashboard import DashboardPage
from .page_misc import LogsPage, SettingsPage
from .page_recorder import RecorderPage
from .page_scheduler import SchedulerPage
from .page_timeline import TimelinePage
from .session import MacroSession
from .theme import stylesheet

PAGES = [("dashboard", "🏠 Dashboard"), ("recorder", "⏺ Macro Recorder"), ("timeline", "☰ Timeline Editor"),
         ("discord", "💬 Discord Manager"), ("scheduler", "📅 Message Scheduler"), ("logs", "📄 Activity Logs"),
         ("settings", "⚙ Settings")]


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        self.session = MacroSession(engine)
        self._really_quit = False
        self._tray_hint_shown = False
        self.setWindowTitle("Nova Macro Hub")
        self.setWindowIcon(app_icon())
        self.resize(1560, 1000)
        self.setMinimumSize(1100, 700)

        self.backdrop = Backdrop()
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)
        self.setCentralWidget(self.backdrop)

        # ---- header: logo, name, tabs, emergency stop
        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(10)
        hl.addWidget(CatLogo(54))
        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel("Nova Macro Hub ♥")
        name.setObjectName("brand")
        tag = muted("Automate. Play. Announce. Together. ♡", wrap=False)
        brand.addWidget(name)
        brand.addWidget(tag)
        name.setMinimumWidth(name.sizeHint().width() + 8)
        tag.setMinimumWidth(tag.sizeHint().width() + 4)
        hl.addLayout(brand)
        hl.addSpacing(18)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons = {}
        for i, (key, label) in enumerate(PAGES):
            b = QPushButton(label)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            self.tab_buttons[key] = b
            hl.addWidget(b)
        hl.addStretch(1)
        self.estop = button("", self.emergency_stop, kind="danger")
        self.estop.setMinimumHeight(38)
        self.estop.setToolTip("Stops all macro playback immediately and releases every key")
        hl.addWidget(self.estop)
        root.addWidget(header)

        # ---- pages
        self.stack = QStackedWidget()
        self.pages = {
            "recorder": RecorderPage(engine, self.session),
            "timeline": TimelinePage(engine, self.session),
            "discord": DiscordPage(engine),
            "scheduler": SchedulerPage(engine),
            "logs": LogsPage(engine),
            "settings": SettingsPage(engine),
        }
        self.pages["dashboard"] = DashboardPage(engine, self.session, self.pages)
        for key, _ in PAGES:
            page = self.pages[key]
            if key == "dashboard":
                self.stack.addWidget(page)
            else:
                frame = QFrame()
                frame.setObjectName("card")
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(4, 4, 4, 4)
                fl.addWidget(page)
                self.stack.addWidget(frame)
        root.addWidget(self.stack, 1)
        self.tab_group.idClicked.connect(self._nav_changed)

        # ---- footer status bar
        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 5, 14, 5)
        fl.setSpacing(10)
        fl.addWidget(QLabel("🐱 Nova Macro Hub v1.0.0"))
        self.pill_rec = QLabel()
        self.pill_play = QLabel()
        self.pill_sched = QLabel()
        for pl in (self.pill_rec, self.pill_play, self.pill_sched):
            pl.setObjectName("pill")
            fl.addWidget(pl)
        fl.addStretch(1)
        self.discord_lbl = QLabel()
        self.sched_lbl = QLabel()
        self.clock_lbl = muted("", wrap=False)
        for w in (self.discord_lbl, self.sched_lbl, self.clock_lbl):
            fl.addWidget(w)
        root.addWidget(footer)
        self.go("dashboard")

        # ---- wiring
        rec: RecorderPage = self.pages["recorder"]
        tl: TimelinePage = self.pages["timeline"]
        dash: DashboardPage = self.pages["dashboard"]
        settings: SettingsPage = self.pages["settings"]
        rec.request_minimize.connect(self.showMinimized)
        rec.request_restore.connect(self.bring_to_front)
        rec.show_timeline.connect(lambda: self.go("timeline"))
        tl.record_here.connect(lambda pos: (self.go("recorder"), rec.start_record(insert_at=pos)))
        tl.play_selection.connect(rec.play_macro)
        dash.goto.connect(self.go)
        settings.theme_changed.connect(self.apply_theme)
        settings.appearance_changed.connect(self._appearance_changed)
        settings.hotkeys_changed.connect(self._hotkeys_changed)
        engine.state_changed.connect(self.update_status)
        engine.schedules_changed.connect(self.update_status)
        engine.hotkey.connect(self._on_hotkey)
        engine.notify.connect(self._notify)
        self.session.changed.connect(lambda _: self._update_title())
        self.session.saved.connect(self._update_title)
        self.session.loaded.connect(self._update_title)

        from .mini_player import MiniPlayer
        self.mini = MiniPlayer(self)
        self.mini_auto = QCheckBox("Mini controller during playback")
        self.mini_auto.setChecked(bool(self.storage.get_setting("mini_playback", False)))
        self.mini_auto.toggled.connect(lambda v: self.storage.set_setting("mini_playback", v))
        fl.insertWidget(0, self.mini_auto)
        fl.insertWidget(1, button("Mini", self.mini.show))
        self._make_tray()
        self.apply_theme(self.storage.get_setting("theme"))
        self._hotkeys_changed()
        self.update_status()
        t = QTimer(self)
        t.timeout.connect(self.update_status)
        t.start(1000)

    # ---- navigation ---------------------------------------------------
    def _nav_changed(self, idx):
        self.stack.setCurrentIndex(idx)
        btn = self.tab_group.button(idx)
        if btn and not btn.isChecked():
            btn.setChecked(True)

    def go(self, key):
        self._nav_changed([k for k, _ in PAGES].index(key))

    def _open_macro(self, mid):
        if self.pages["recorder"]._check_unsaved():
            self.session.open(mid)
            self.go("timeline")

    def _play_saved(self, mid):
        m = self.storage.load_macro(mid)
        if m:
            self.pages["recorder"].play_macro(m)

    def _update_title(self):
        m = self.session.macro
        self.setWindowTitle(f"Nova Macro Hub — {m.name}{' *' if self.session.dirty else ''}")

    def apply_theme(self, name):
        CURRENT_THEME["name"] = name if name in ("dark", "light") else "dark"
        QApplication.instance().setStyleSheet(stylesheet(CURRENT_THEME["name"]))
        self.backdrop.refresh_theme()
        self._appearance_changed()

    def _appearance_changed(self):
        self.backdrop.set_image(self.storage.get_setting("background_image", None))
        self.pages["dashboard"].mascot.reload()

    def _hotkeys_changed(self):
        self.estop.setText(f"⛔ STOP ALL  ({keynames.hotkey_label(self.storage.get_setting('hotkey_stop'))})")
        self.pages["recorder"].update_hints()
        self.pages["dashboard"].refresh_hotkeys()
        self._rebuild_tray_menu()

    # ---- status -------------------------------------------------------
    def update_status(self):
        e = self.engine
        if e.recording:
            set_pill(self.pill_rec, "● Recording (paused)" if e.recorder.paused else "● Recording", "rec")
        else:
            set_pill(self.pill_rec, "Ready", "")
        if e.player.playing:
            set_pill(self.pill_play, f"▶ Playing: {e.now_playing}", "play")
        else:
            set_pill(self.pill_play, "Not playing", "")
        scheds = self.storage.list_schedules()
        n_msg = sum(1 for s in scheds if s["enabled"] and s["job"] == "message")
        n_mac = sum(1 for s in scheds if s["enabled"] and s["job"] == "macro")
        if e.scheduler.messages_paused and n_msg:
            set_pill(self.pill_sched, f"⏸ {n_msg} announcement(s) paused", "warn")
        elif e.scheduler.macros_paused:
            set_pill(self.pill_sched, "⚠ Macro schedules paused (emergency stop)", "warn")
        elif n_msg or n_mac:
            set_pill(self.pill_sched, f"📅 Scheduler on: {n_msg} message(s), {n_mac} macro run(s)", "sched")
        else:
            set_pill(self.pill_sched, "Scheduler idle", "")
        tok = bool(self.storage.get_setting("bot_name", None))  # set when a bot token is saved and tested
        n_targets = len(self.storage.list_targets())
        if tok or n_targets:
            self.discord_lbl.setText("<span style='color:#2bd47a'>●</span> Discord " + ("Connected" if tok else "Webhooks ready"))
        else:
            self.discord_lbl.setText("<span style='color:#ff6b8f'>●</span> Discord not set up")
        self.sched_lbl.setText(f"⏰ {n_msg} Scheduled Message{'s' if n_msg != 1 else ''}")
        now = datetime.now()
        self.clock_lbl.setText(now.strftime("%b %d, %Y  %I:%M %p").replace(" 0", " "))
        if hasattr(self, "tray"):
            state = "rec" if e.recording else "play" if e.player.playing else "idle"
            if state != getattr(self, "_tray_state", None):
                self._tray_state = state
                self.tray.setIcon(tray_icon(state))
            self.tray.setToolTip(f"Nova Macro Hub — {self.pill_rec.text()}, {self.pill_play.text()}, {self.pill_sched.text()}")
            self._update_tray_actions()

    # ---- actions ------------------------------------------------------
    def emergency_stop(self):
        self.pages["recorder"].cancel_countdown()
        self.engine.emergency_stop(source="button")

    def _on_hotkey(self, name):
        rec: RecorderPage = self.pages["recorder"]
        if name == "record":
            rec.toggle_record()
        elif name == "pause":
            rec.toggle_pause()
        elif name == "play":
            rec.toggle_play()
        elif name == "stop":
            rec.cancel_countdown()
            self.update_status()

    def _notify(self, title, msg):
        if hasattr(self, "tray") and self.tray.isVisible():
            self.tray.showMessage(title, msg, QSystemTrayIcon.Warning, 8000)

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---- tray ---------------------------------------------------------
    def _make_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(tray_icon("idle"), self)
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason: reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
                                    and self.bring_to_front())
        self._rebuild_tray_menu()
        self.tray.show()

    def _rebuild_tray_menu(self):
        if not hasattr(self, "tray"):
            return
        m = self.tray_menu
        m.clear()
        rec: RecorderPage = self.pages["recorder"]
        m.addAction("Open Nova Macro Hub", self.bring_to_front)
        m.addSeparator()
        self.t_estop = m.addAction(f"⛔ EMERGENCY STOP ({keynames.hotkey_label(self.storage.get_setting('hotkey_stop'))})",
                                   self.emergency_stop)
        self.t_rec = m.addAction("● Start recording", lambda: rec.stop_record("tray") if self.engine.recording
                                 else rec.start_record())
        self.t_play = m.addAction("▶ Play current macro", rec.toggle_play)
        m.addSeparator()
        self.t_pause = m.addAction("⏸ Pause all announcements",
                                   lambda: self.engine.set_messages_paused(not self.engine.scheduler.messages_paused))
        self.t_resume_mac = m.addAction("Resume macro schedules", self.engine.resume_macro_schedules)
        m.addSeparator()
        m.addAction("Quit (stops all schedules)", self.quit_app)
        self._update_tray_actions()

    def _update_tray_actions(self):
        if not hasattr(self, "t_rec"):
            return
        e = self.engine
        self.t_rec.setText("■ Stop recording" if e.recording else "● Start recording")
        self.t_play.setText("■ Stop playback" if e.player.playing else f"▶ Play '{self.session.macro.name}'")
        self.t_pause.setText("▶ Resume all announcements" if e.scheduler.messages_paused else "⏸ Pause all announcements")
        self.t_resume_mac.setVisible(e.scheduler.macros_paused)

    # ---- closing ------------------------------------------------------
    def closeEvent(self, ev: QCloseEvent):
        if not self._really_quit and self.storage.get_setting("minimize_to_tray") and hasattr(self, "tray"):
            ev.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("Nova Macro Hub is still running",
                                      "Schedules and hotkeys keep working. Right-click the tray icon to quit.",
                                      QSystemTrayIcon.Information, 5000)
            return
        if not self._confirm_quit():
            self._really_quit = False
            ev.ignore()
            return
        self._shutdown()
        ev.accept()

    def _confirm_quit(self) -> bool:
        if self.session.dirty and self.session.macro.actions:
            choice = confirm(self, "Unsaved macro", f"Save '{self.session.macro.name}' before quitting?",
                             yes="Save", no="Don't save")
            if choice:
                try:
                    self.session.save()
                except Exception:
                    pass
        active = sum(1 for s in self.storage.list_schedules() if s["enabled"])
        if active:
            return confirm(self, "Quit Nova Macro Hub?", f"{active} schedule(s) are on. They only run while the app is open. "
                           "Quit anyway?", yes="Quit", no="Keep running")
        return True

    def quit_app(self):
        self._really_quit = True
        if not self._confirm_quit():
            self._really_quit = False
            return
        self._shutdown()
        QApplication.instance().quit()

    def _shutdown(self):
        if getattr(self, "_down", False):
            return
        self._down = True
        if hasattr(self, "tray"):
            self.tray.hide()
        self.engine.shutdown()
