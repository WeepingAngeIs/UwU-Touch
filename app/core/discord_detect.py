"""Find which channel is open in the Discord desktop app.

Discord shows the open channel in its window title, e.g.
"#guild-announcements | My Guild - Discord". We read that title (read-only,
nothing is injected into Discord) and, if a bot is configured, look the names
up through the bot to get the channel ID. The user always confirms the result.
"""
from __future__ import annotations

import re
import sys

TITLE_RE = re.compile(r"^(?:\(\d+\)\s*)?(?:•\s*)?#?(?P<channel>[^|]+?)\s*\|\s*(?P<server>.+?)\s*-\s*Discord(?: PTB| Canary)?$")
DISCORD_EXES = {"discord.exe", "discordptb.exe", "discordcanary.exe"}


def parse_title(title: str):
    """Return (channel_name, server_name) or None (DMs, home screen, etc.)."""
    title = (title or "").strip()
    m = TITLE_RE.match(title)
    if not m:
        return None
    channel = m.group("channel").strip().lstrip("#").strip()
    server = m.group("server").strip()
    if not channel or channel.startswith("@"):
        return None
    return channel, server


def discord_window_titles() -> list[str]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    titles = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def exe_of(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            kernel32.CloseHandle(h)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        t = buf.value
        if "Discord" in t and exe_of(hwnd) in DISCORD_EXES:
            titles.append(t)
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return titles


def detect_open_channel():
    """Returns (channel_name, server_name, raw_title) or None."""
    for t in discord_window_titles():
        parsed = parse_title(t)
        if parsed:
            return parsed[0], parsed[1], t
    return None


def match_channel(client, token, channel_name: str, server_name: str):
    """Use the bot to find (guild, channel) dicts matching the names. Returns list of matches."""
    matches = []
    for g in client.bot_guilds(token):
        if g.get("name", "").strip().lower() != server_name.strip().lower():
            continue
        for c in client.guild_text_channels(token, g["id"]):
            if c.get("name", "").lower() == channel_name.lower():
                matches.append((g, c))
    return matches
