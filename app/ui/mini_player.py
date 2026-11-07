"""Compact controller sharing the editor's playback and recording state."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from ..core.models import format_clock
from .common import button

class MiniPlayer(QWidget):
    def __init__(self, main):
        super().__init__(main, Qt.Window | Qt.WindowStaysOnTopHint)
        self.main = main
        self.was_playing = False
        self.setWindowTitle("Nova - Mini controller")
        self.resize(420, 160)
        layout = QVBoxLayout(self)
        self.status = QLabel("Ready")
        self.clock = QLabel("00:00.00")
        self.clock.setStyleSheet("font-size: 28px; font-family: Consolas;")
        layout.addWidget(self.status)
        layout.addWidget(self.clock)
        controls = QHBoxLayout()
        rec = main.pages["recorder"]
        self.play = button("Play", rec.play)
        self.record = button("Record", rec.start_record)
        for b in (self.play, button("Stop", self.stop), self.record, button("Full editor", self.expand)):
            controls.addWidget(b)
        layout.addLayout(controls)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def stop(self):
        rec = self.main.pages["recorder"]
        rec.cancel_countdown()
        if self.main.engine.recording:
            rec.stop_record("button")
        self.main.engine.player.stop(wait=0)

    def expand(self):
        self.hide()
        self.main.bring_to_front()

    def tick(self):
        engine = self.main.engine
        playing = engine.player.playing
        rec = self.main.pages["recorder"]
        if playing and not self.was_playing and self.main.mini_auto.isChecked():
            self.main.showMinimized()
            self.showNormal()
        self.was_playing = playing
        counting = bool(rec._countdown_left)
        self.play.setEnabled(not playing and not engine.recording and not counting)
        self.record.setEnabled(not playing and not engine.recording and not counting)
        if counting:
            self.status.setText(rec.status.text())
        elif engine.recording:
            self.status.setText("Recording paused" if engine.recorder.paused else "Recording")
            self.clock.setText(format_clock(engine.recorder.elapsed()))
        else:
            self.status.setText("Playing - elapsed" if playing else "Stopped - elapsed")
            self.clock.setText(format_clock(engine.player.elapsed()))
