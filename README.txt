NOVA MACRO HUB  -  Macro Recorder, Timeline Editor & Discord Announcer
=======================================================================
Version 1.0.0  -  for Windows 10 / 11


-----------------------------------------------------------------------
1. INSTALL (one time)
-----------------------------------------------------------------------
1. Unzip the folder somewhere you keep it, e.g.  Documents\NovaMacroHub
   (right-click the zip - Extract All - Extract).
2. Double-click  "1 - Install (first time).bat".
   - If Python is missing it offers to install it. Let it, then run the
     same file again.
   - It downloads about 90 MB. On slow internet this can take a while. If it
     fails, just run it again - it carries on where it stopped.
3. When it says Done, double-click  "2 - Start Nova Macro Hub.bat".

Want a real .exe?
   Double-click  "3 - Build EXE.bat"  (after step 2 above). When it finishes,
   a folder opens with  NovaMacroHub.exe . Keep that whole folder together.
   Right-click the .exe - Send to - Desktop (create shortcut).
   (The .exe has to be built on your own PC - it can't be built for you
   from outside Windows.)


-----------------------------------------------------------------------
2. QUICK START: RECORD, EDIT, PLAY
-----------------------------------------------------------------------
Default hotkeys (work while your game is in front):
   F9  = start / stop recording        F10 = pause / resume recording
   F11 = play / stop current macro     F8  = EMERGENCY STOP (everything)
Change them in Settings - Global hotkeys (click the button, press new keys).

Record:
1. Dashboard (or Macro Recorder tab) - click  Record.
2. A 3-second countdown starts and the window minimizes - click into your game.
3. Do your keys/clicks. Press F9 to stop.
4. The steps appear in the Timeline. Click  Save  (the floppy icon).

Edit timing (Timeline Editor tab, or the Dashboard timeline):
- Double-click a "Delay Before" value - type the new seconds - Enter.
  Every later timestamp moves automatically.
- Double-click a "Timestamp" to move a step to an exact time.
- Seconds/milliseconds switch: top-right of the Timeline Editor tab.
- Select several rows (Ctrl+click / Shift+click) - "Set delay..." to give them
  all the same delay, "Shift..." to add/remove time, "Scale..." to speed up.
- Drag rows to reorder. Right-click a row for everything else.
- Add Action / Insert Delay add new steps after the selected row.
- Copy / Paste / Duplicate / Delete, Undo (Ctrl+Z) / Redo (Ctrl+Y).
- "Record into here" records new actions and inserts them after the
  selected row (existing steps stay).
- Dashboard - Action Editor (right side): pick one step, change anything,
  click  Apply changes.
- "Thin mouse moves" removes extra mouse-movement steps without changing
  when any click or key happens.

Play:
- Playback Options: speed (0.25x - 4x), repeat count, "Loop until stopped",
  "Delay between loops". These are saved with the macro.
- Click Play (or F11). F8 / STOP ALL stops instantly and releases every key.

Profiles: the Profile box switches between saved macros. Import/Export
JSON is in the Macro Recorder tab (Discord passwords are never exported).

Run a macro at set times: Message Scheduler tab - "Macro runs" - Schedule a
macro (e.g. every day at 6:00 PM). After an Emergency Stop, macro schedules
pause until you click "Resume macro schedules".


-----------------------------------------------------------------------
3. DISCORD SETUP
-----------------------------------------------------------------------
You need ONE of these. A webhook is the easiest.

A) WEBHOOK  (easiest, no bot needed)
1. In Discord: right-click your server - Server Settings - Integrations -
   Webhooks - New Webhook.
2. Click the new webhook - pick the channel (e.g. #guild-announcements) -
   Copy Webhook URL.
3. In Nova Macro Hub: Discord Manager - "+ Webhook..." - paste the URL - OK.
4. Select it - "Send to selected channel" to test.
Repeat for each channel you want to post in.

B) BOT  (lets you add channels by ID, browse channels, and detect the
   channel open in Discord)
1. Go to https://discord.com/developers/applications - New Application -
   name it - Create.
2. Left menu "Bot" - "Reset Token" - Copy. (Keep it secret!)
3. Nova Macro Hub - Discord Manager - paste it in the Bot box -
   "Save & test".
4. Click "Copy invite link", paste it in your browser, pick your server -
   Authorize. (It only asks for View Channel + Send Messages.)
5. Add channels:
   - "Browse bot's servers..." and pick one, or
   - "+ Channel ID / link...": in Discord right-click the channel -
     Copy Link - click Paste, or
   - "Detect open Discord channel...": open the channel in the Discord app
     first. The app reads the channel name from Discord's window title, finds
     it through your bot, and asks you to confirm before saving it.

Bot token and webhook URLs are stored in Windows Credential Manager, not in
any file you might share.

Your own bot from another project can be used here too: paste its token.
It just needs Send Messages permission in the channel.


-----------------------------------------------------------------------
4. SCHEDULED ANNOUNCEMENTS
-----------------------------------------------------------------------
Message Scheduler - "+ New announcement":
- Name, channel, message (any text and emoji, up to 2000 characters).
- Tick "Allow @everyone / @here" if the message should ping people.
- When:  Repeat every 5/10/15/30 min, 1/2/3/6/12/24 hours or Custom
         (seconds, minutes, hours, days)
         At set times of day + which weekdays
         One time on a date
  Optional "Start at" and "Stop after". The preview shows the next 5 sends.
- "Send test now" checks it before you switch it on.
- Flip the switch to turn each message on/off. "Last sent" and "Next send"
  are shown for every message.

Example from the raid use case:
   Message 1: "⚔️ RAID IN 30 MINUTES! GET READY!"  - At set times: 5:30 PM
   Message 2: "🔥 RAID TIME! EVERYONE LOG IN NOW!" - At set times: 6:00 PM
   (Use "Duplicate" to copy the first one and just change text and time.)

Discord steps inside macros: Timeline - Add Action - "Send Discord message".
Example: wait 600 s, then send "Raid is starting now!".

Keep the app running: closing the window sends it to the system tray
(bottom-right, maybe under the ^ arrow). Right-click the tray icon for
Emergency Stop, Pause all announcements, or Quit. Settings - "Start with
Windows" keeps announcements working after a reboot.


-----------------------------------------------------------------------
5. SAFETY FEATURES
-----------------------------------------------------------------------
- Emergency stop: F8, the STOP ALL button, Quick Actions - Stop All, or the
  tray menu. Playback stops between any two steps and every held key/mouse
  button is released. It works even while a macro is holding Shift etc.
- Discord rate limits are respected automatically (waits and retries).
- Flood protection: max messages per channel per minute (Settings).
- Shortest repeat interval allowed (Settings, default 10 s).
- No duplicates: each scheduled send is recorded before it is sent. After a
  crash/restart or connection drop, a message is never sent twice.
- Missed messages (PC asleep, app closed) are skipped and logged instead of
  all being sent at once later (Settings - "Send late messages if less than").
- Only one copy of the app can run at a time.
- Everything is saved automatically in  %APPDATA%\NovaMacroHub
  (macros and schedules are in the SQLite database novamacrohub.db).


-----------------------------------------------------------------------
6. LOOK & FEEL
-----------------------------------------------------------------------
Settings - Appearance:
- Theme: Dark (neon night) or Light (sakura).
- Background picture: any picture of your own, or the built-in blossoms.
- Mascot picture: replaces the cat in the System Tray card (a PNG with a
  transparent background looks best).


-----------------------------------------------------------------------
7. TROUBLESHOOTING
-----------------------------------------------------------------------
Keys don't work in my game
  - If the game runs as Administrator, run Nova Macro Hub as Administrator
    too (right-click - Run as administrator). Windows blocks input from
    normal apps into admin apps.
  - Settings - Key sending: try the other mode.
  - Some online games block all simulated input (anti-cheat). Nothing on
    the app side can change that - check your game's rules on macros.

Mouse clicks land in the wrong place
  - Don't change Windows display scaling or resolution between recording
    and playing. Re-record or edit the X/Y in the Action Editor.
  - Use "Pick position" in the Action Editor to capture a spot.

Hotkeys don't react
  - Another program may use the same key - pick a different one in Settings.
  - If the game runs as Administrator, run this app as Administrator.

"Discord rejected the bot token (401)"  - Reset the token in the Developer
   Portal and paste the new one.
"not allowed to post in this channel (403)" - In Discord: channel settings -
   Permissions - add your bot - allow View Channel + Send Messages.
"Webhook not found (404)" - the webhook was deleted. Make a new one and use
   "Change webhook / ID..." in Discord Manager.
"Channel not found (404)" - wrong ID, or the bot isn't in that server.
"Flood protection ..." - you hit the per-minute limit; raise it in Settings
   if that was on purpose.
"Skipped ... the app was closed" - see Settings - Send late messages if
   less than ... minutes.

Detect open Discord channel finds nothing
  - Open a SERVER text channel (not a DM) in the Discord desktop app, then
    try again. Or use "+ Channel ID / link..." with Copy Link.

Install fails with red text
  - Usually the internet connection. Run "1 - Install (first time).bat"
    again. If it keeps failing, restart the PC and try again.

The app seems gone after closing
  - It's in the tray. Click the ^ arrow at the bottom-right of the taskbar.

Something else
  - Activity Logs tab shows every action and error. "Export..." saves them
    to a text file. Crash details are in %APPDATA%\NovaMacroHub\app.log


-----------------------------------------------------------------------
8. FOR DEVELOPERS
-----------------------------------------------------------------------
Manual setup:   python -m venv .venv
                .venv\Scripts\pip install -r requirements.txt
Run:            .venv\Scripts\python run.py
Tests:          .venv\Scripts\pip install pytest
                .venv\Scripts\python -m pytest -q tests
                (or double-click "4 - Run tests.bat")
EXE:            "3 - Build EXE.bat" (PyInstaller, one-folder build)

Project layout
  run.py                    start the app
  app/main.py               startup, single-instance lock, error logging
  app/engine.py             connects everything; Qt signals for threads
  app/core/models.py        Action / Macro / playback settings, JSON format
  app/core/timeline.py      editing operations + undo/redo
  app/core/recorder.py      global keyboard/mouse recording (pynput)
  app/core/player.py        playback thread, exact timing, emergency stop
  app/core/inputs.py        Windows SendInput (scan codes for games)
  app/core/hotkeys.py       global hotkeys
  app/core/storage.py       SQLite database
  app/core/secrets_store.py Windows Credential Manager / DPAPI
  app/core/discord_client.py webhooks + bot API, rate limits, flood guard
  app/core/discord_detect.py open-channel detection from the Discord window
  app/core/schedule.py      schedule math (next run times)
  app/core/scheduler.py     background scheduler, duplicate protection
  app/ui/                   the interface (one file per tab)
  tests/                    timing, timeline editing, scheduling, delivery,
                            and interface tests

Threads: recording (pynput listeners), playback (own thread), scheduler
(own thread + 4 send workers) and all Discord calls from the interface run
in the background, so the window never freezes.
