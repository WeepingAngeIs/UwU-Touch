# UwU Touch — Nova Macro Hub

Windows macro recorder, timeline editor and compact playback controller.

Install Python 3.12 or newer, then run `1 - Install (first time).bat` and `2 - Start Nova Macro Hub.bat`. See README.txt for the detailed guide.

The dashboard and recorder show live elapsed playback time, including waits and repeated loops. The Mini button opens an always-on-top controller with Play, Stop, Record and Full editor. Enable **Mini controller during playback** to open it automatically when playback begins. F8 remains the default emergency stop. Closing the mini window hides it; use Stop to stop playback.

Source lives in app/, artwork in assets/, and tests in tests/. GitHub Actions runs tests with fake input devices. Keep heavy tests and builds on hosted runners. Personal macros and credentials are stored separately from this source repository.
