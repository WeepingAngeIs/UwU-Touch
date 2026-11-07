"""Discord Manager: bot token, channels (webhook or bot + channel ID), test messages."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import discord_client as dc
from ..core.discord_detect import detect_open_channel, match_channel
from .common import button, card, confirm, error_box, info_box, muted, page_layout, row, run_async

PERMS = 1024 | 2048  # View Channel + Send Messages


class DiscordPage(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.storage = engine.storage
        lay = page_layout(self, "Discord Manager",
                          "Set up where messages go. A webhook is the easiest (no bot needed). A bot lets you "
                          "pick channels by ID and detect the channel open in Discord.")

        # ---- bot card
        bc, bl = card("Bot (optional)")
        self.bot_status = muted("")
        bl.addWidget(self.bot_status)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Paste your bot token here (Discord Developer Portal → Bot → Reset Token)")
        bl.addLayout(row(self.token, button("Save && test", self._save_token, kind="primary"),
                         button("Remove", self._remove_token)))
        self.invite_b = button("Copy invite link", self._copy_invite,
                               tip="Link to add the bot to your server with only View Channel + Send Messages")
        bl.addLayout(row(button("Open Developer Portal", lambda: QDesktopServices.openUrl(
            QUrl("https://discord.com/developers/applications"))), self.invite_b, None))
        lay.addWidget(bc)

        # ---- channels card
        cc, cl = card("Channels", "Each channel you add can be used by scheduled messages and by Discord steps in macros.")
        cl.addLayout(row(button("＋ Webhook…", lambda: self._add_webhook(), kind="primary"),
                         button("＋ Channel ID / link…", lambda: self._add_channel()),
                         button("🔍 Detect open Discord channel…", self._detect),
                         button("Browse bot's servers…", self._browse), None))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Server", "Channel", "Test"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        cl.addWidget(self.table, 1)
        cl.addLayout(row(button("Rename…", self._rename), button("Change webhook / ID…", self._change),
                         button("Delete", self._delete_target), None))
        lay.addWidget(cc, 1)

        # ---- test card
        tc, tl = card("Test message")
        self.test_text = QPlainTextEdit("✅ Nova Macro Hub test message — this channel is set up!")
        self.test_text.setFixedHeight(60)
        tl.addWidget(self.test_text)
        self.test_b = button("Send to selected channel", self._send_test, kind="primary")
        tl.addLayout(row(self.test_b, None))
        lay.addWidget(tc)

        self.refresh()
        self._refresh_bot_label()

    # ---- refresh ------------------------------------------------------
    def refresh(self):
        sel = self.selected_id()
        targets = self.storage.list_targets()
        self.table.setRowCount(len(targets))
        for r, t in enumerate(targets):
            vals = [t["name"], "Webhook" if t["kind"] == "webhook" else "Bot",
                    t["guild_name"] or "—", ("#" + t["channel_name"]) if t["channel_name"] else (t["channel_id"] or "—"),
                    "✔ OK" if t["last_test_ok"] else "not tested"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, t["id"])
                self.table.setItem(r, c, it)
            if t["id"] == sel:
                self.table.selectRow(r)

    def selected_id(self):
        items = self.table.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _refresh_bot_label(self):
        tok = self.engine.bot_token()
        name = self.storage.get_setting("bot_name", None)
        if tok:
            self.bot_status.setText(f"Bot saved securely ({self.engine.secrets.backend_name})"
                                    + (f" — connected as {name}" if name else ""))
            self.token.setPlaceholderText("Token saved. Paste a new one to replace it.")
        else:
            self.bot_status.setText("No bot set up. You only need one for 'Channel ID' channels and detection.")
        self.invite_b.setEnabled(bool(self.storage.get_setting("bot_id", None)))

    # ---- bot ----------------------------------------------------------
    def _save_token(self):
        tok = self.token.text().strip()
        if tok.lower().startswith("bot "):
            tok = tok[4:].strip()
        if not tok:
            tok = self.engine.bot_token()
            if not tok:
                return error_box(self, "Bot token", "Paste the bot token first.")

        def done(res, err):
            if err:
                return error_box(self, "Bot token not accepted", err)
            self.engine.secrets.set("bot_token", tok)
            self.storage.set_setting("bot_name", res.get("username"))
            self.storage.set_setting("bot_id", res.get("id"))
            self.token.clear()
            self.engine.log.info("Discord", f"Bot token saved (bot: {res.get('username')}).")
            self._refresh_bot_label()
            info_box(self, "Bot connected", f"Connected as {res.get('username')}.\n\nIf the bot is not in your server yet, "
                     "click 'Copy invite link', paste it in your browser and pick your server.")

        self.bot_status.setText("Checking token…")
        run_async(self.engine.discord.bot_identity, tok, on_done=done)

    def _remove_token(self):
        if confirm(self, "Remove bot", "Remove the saved bot token? Bot channels will stop working.", yes="Remove"):
            self.engine.secrets.delete("bot_token")
            self.storage.set_setting("bot_name", None)
            self._refresh_bot_label()

    def _copy_invite(self):
        bid = self.storage.get_setting("bot_id", None)
        if not bid:
            return
        url = f"https://discord.com/oauth2/authorize?client_id={bid}&scope=bot&permissions={PERMS}"
        QGuiApplication.clipboard().setText(url)
        info_box(self, "Invite link copied", "Paste it into your browser, choose your guild's server and click Authorize.")

    def _need_bot(self):
        tok = self.engine.bot_token()
        if not tok:
            error_box(self, "Bot needed", "This needs a bot. Paste a bot token in the Bot box above, "
                      "or add the channel with a webhook instead.")
        return tok

    # ---- add channels ------------------------------------------------
    def _add_webhook(self, existing=None):
        d = QDialog(self)
        d.setWindowTitle("Add webhook channel")
        lay = QVBoxLayout(d)
        lay.addWidget(muted("In Discord: Server Settings → Integrations → Webhooks → New Webhook → pick the channel → "
                            "Copy Webhook URL. Paste it below."))
        f = QFormLayout()
        name = QLineEdit(existing["name"] if existing else "")
        name.setPlaceholderText("e.g. Guild announcements")
        url = QLineEdit()
        url.setPlaceholderText("https://discord.com/api/webhooks/…")
        url.setEchoMode(QLineEdit.Password if existing else QLineEdit.Normal)
        f.addRow("Name", name)
        f.addRow("Webhook URL", url)
        lay.addLayout(f)
        status = muted("")
        lay.addWidget(status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(bb)
        bb.rejected.connect(d.reject)

        def ok():
            u = url.text().strip()
            if not dc.parse_webhook(u):
                return status.setText("⚠ That doesn't look like a Discord webhook URL.")
            status.setText("Checking webhook…")
            bb.setEnabled(False)

            def done(info, err):
                bb.setEnabled(True)
                if err:
                    return status.setText(f"⚠ {err}")
                nm = name.text().strip() or info.get("name") or "Webhook"
                if existing:
                    tid = existing["id"]
                    self.storage.update_target(tid, name=nm, channel_id=info.get("channel_id"),
                                               guild_id=info.get("guild_id"), last_test_ok=0)
                else:
                    tid = self.storage.add_target(nm, "webhook", info.get("channel_id"), info.get("guild_id"))
                self.engine.secrets.set(f"webhook:{tid}", u)
                self.engine.log.info("Discord", f"Webhook channel '{nm}' saved.")
                d.accept()

            run_async(self.engine.discord.webhook_info, u, on_done=done)

        bb.accepted.connect(ok)
        d.setMinimumWidth(520)
        if d.exec():
            self.refresh()

    def _add_channel(self, prefill_id="", prefill_name="", existing=None):
        if not self._need_bot():
            return
        d = QDialog(self)
        d.setWindowTitle("Add channel by ID or link")
        lay = QVBoxLayout(d)
        lay.addWidget(muted("Easiest: in Discord right-click the channel → Copy Link, then click 'Paste'. "
                            "(Or turn on Developer Mode and use Copy Channel ID.)"))
        f = QFormLayout()
        name = QLineEdit(prefill_name or (existing["name"] if existing else ""))
        cid = QLineEdit(prefill_id or (existing["channel_id"] if existing else ""))
        cid.setPlaceholderText("123456789012345678  or  https://discord.com/channels/…/…")
        paste = button("Paste", lambda: cid.setText(QGuiApplication.clipboard().text().strip()))
        f.addRow("Name", name)
        f.addRow("Channel ID / link", _h(cid, paste))
        lay.addLayout(f)
        status = muted("")
        lay.addWidget(status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(bb)
        bb.rejected.connect(d.reject)
        tok = self.engine.bot_token()

        def ok():
            text = cid.text().strip()
            link = dc.parse_channel_link(text)
            channel_id = link[1] if link else text
            if not dc.is_snowflake(channel_id):
                return status.setText("⚠ Paste a channel link or a long number ID.")
            status.setText("Checking channel with the bot…")
            bb.setEnabled(False)

            def lookup():
                info = self.engine.discord.channel_info(tok, channel_id)
                gname = None
                try:
                    for g in self.engine.discord.bot_guilds(tok):
                        if g["id"] == info.get("guild_id"):
                            gname = g["name"]
                except Exception:
                    pass
                return info, gname

            def done(res, err):
                bb.setEnabled(True)
                if err:
                    return status.setText(f"⚠ {err}")
                info, gname = res
                nm = name.text().strip() or f"#{info.get('name', channel_id)}"
                if existing:
                    self.storage.update_target(existing["id"], name=nm, channel_id=channel_id,
                                               guild_id=info.get("guild_id"), channel_name=info.get("name"),
                                               guild_name=gname, last_test_ok=0)
                else:
                    self.storage.add_target(nm, "bot", channel_id, info.get("guild_id"), info.get("name"), gname)
                self.engine.log.info("Discord", f"Channel '{nm}' saved.")
                d.accept()

            run_async(lookup, on_done=done)

        bb.accepted.connect(ok)
        d.setMinimumWidth(540)
        if d.exec():
            self.refresh()

    def _detect(self):
        found = detect_open_channel()
        if not found:
            return info_box(self, "No channel detected",
                            "Couldn't read an open server channel from the Discord app.\n\n"
                            "Make sure the Discord desktop app is open on a server text channel (not a DM), "
                            "or use '＋ Channel ID / link…': right-click the channel in Discord → Copy Link.")
        ch, server, title = found
        tok = self.engine.bot_token()
        if not tok:
            return info_box(self, "Channel detected",
                            f"Discord is showing #{ch} in “{server}”.\n\nTo send there, either add a webhook for that "
                            "channel, or set up a bot (then detection can fill in the channel automatically).")

        def done(matches, err):
            if err:
                return error_box(self, "Detection", err)
            if not matches:
                return info_box(self, "Not found", f"Discord shows #{ch} in “{server}”, but your bot can't see that "
                                "channel. Invite the bot to that server (Copy invite link), or check its permissions.")
            g, c = matches[0]
            extra = f"\n\n({len(matches)} channels share this name; the first was picked.)" if len(matches) > 1 else ""
            if confirm(self, "Confirm channel", f"Use this channel?\n\nServer: {g['name']}\nChannel: #{c['name']}\n"
                       f"ID: {c['id']}{extra}", yes="Yes, add it"):
                self.storage.add_target(f"#{c['name']}", "bot", c["id"], g["id"], c["name"], g["name"])
                self.engine.log.info("Discord", f"Added detected channel #{c['name']} ({g['name']}).")
                self.refresh()

        run_async(match_channel, self.engine.discord, tok, ch, server, on_done=done)

    def _browse(self):
        tok = self._need_bot()
        if not tok:
            return
        d = QDialog(self)
        d.setWindowTitle("Pick a channel")
        lay = QVBoxLayout(d)
        guilds = QComboBox()
        chans = QListWidget()
        status = muted("Loading servers…")
        lay.addWidget(QLabel("Server"))
        lay.addWidget(guilds)
        lay.addWidget(QLabel("Text channels the bot can see"))
        lay.addWidget(chans, 1)
        lay.addWidget(status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)

        def got_guilds(gs, err):
            if err:
                return status.setText(f"⚠ {err}")
            if not gs:
                return status.setText("The bot is not in any server yet. Use 'Copy invite link' first.")
            status.setText("")
            for g in gs:
                guilds.addItem(g["name"], g["id"])

        def load_channels():
            chans.clear()
            gid = guilds.currentData()
            if not gid:
                return
            status.setText("Loading channels…")

            def got(cs, err):
                if err:
                    return status.setText(f"⚠ {err}")
                status.setText("")
                for c in cs:
                    it = QListWidgetItem(f"#{c['name']}")
                    it.setData(Qt.UserRole, c)
                    chans.addItem(it)
            run_async(self.engine.discord.guild_text_channels, tok, gid, on_done=got)

        guilds.currentIndexChanged.connect(lambda _: load_channels())

        def ok():
            it = chans.currentItem()
            if not it:
                return status.setText("Pick a channel.")
            c = it.data(Qt.UserRole)
            self.storage.add_target(f"#{c['name']}", "bot", c["id"], guilds.currentData(), c["name"], guilds.currentText())
            self.engine.log.info("Discord", f"Added channel #{c['name']} ({guilds.currentText()}).")
            d.accept()

        bb.accepted.connect(ok)
        chans.itemDoubleClicked.connect(lambda _: ok())
        run_async(self.engine.discord.bot_guilds, tok, on_done=got_guilds)
        d.resize(420, 480)
        if d.exec():
            self.refresh()

    # ---- edit / delete / test ----------------------------------------
    def _rename(self):
        tid = self.selected_id()
        if not tid:
            return
        from PySide6.QtWidgets import QInputDialog
        t = self.storage.get_target(tid)
        name, ok = QInputDialog.getText(self, "Rename channel", "Name:", text=t["name"])
        if ok and name.strip():
            self.storage.update_target(tid, name=name.strip())
            self.refresh()

    def _change(self):
        tid = self.selected_id()
        if not tid:
            return
        t = self.storage.get_target(tid)
        if t["kind"] == "webhook":
            self._add_webhook(existing=t)
        else:
            self._add_channel(existing=t)

    def _delete_target(self):
        tid = self.selected_id()
        if not tid:
            return
        t = self.storage.get_target(tid)
        if confirm(self, "Delete channel", f"Delete '{t['name']}'? Schedules that use it will be switched off.", yes="Delete"):
            self.engine.secrets.delete(f"webhook:{tid}")
            self.storage.delete_target(tid)
            self.engine.log.info("Discord", f"Deleted channel '{t['name']}'.")
            self.refresh()
            self.engine.schedules_changed.emit()

    def _send_test(self):
        tid = self.selected_id()
        if not tid:
            return info_box(self, "Test message", "Select a channel in the list first.")
        self.test_b.setEnabled(False)
        self.test_b.setText("Sending…")

        def done(res, err):
            self.test_b.setEnabled(True)
            self.test_b.setText("Send to selected channel")
            self.refresh()
            if err or not res.ok:
                return error_box(self, "Test failed", err or res.error)
            info_box(self, "Sent", "Test message sent. Check the channel in Discord.")

        run_async(self.engine.test_target, tid, self.test_text.toPlainText().strip() or "Test", on_done=done)


def _h(*ws):
    from PySide6.QtWidgets import QHBoxLayout
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in ws:
        h.addWidget(x)
    return w
