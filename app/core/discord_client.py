"""Discord sending through webhooks or an authorized bot (official HTTP API only).

Handles:
  * Discord rate limits (429 + X-RateLimit headers) with automatic waiting/retry
  * temporary network / server errors with backoff
  * duplicate protection on retries (bot messages use Discord's enforce_nonce)
  * a local flood guard (max messages per minute per channel)
  * friendly error messages
"""
from __future__ import annotations

import collections
import hashlib
import re
import threading
import time
from dataclasses import dataclass

import requests

API = "https://discord.com/api/v10"
MAX_LEN = 2000
WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/(\d+)/([\w-]+)/?$")
CHANNEL_LINK_RE = re.compile(r"discord(?:app)?\.com/channels/(\d+|@me)/(\d+)")
SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")
USER_AGENT = "DiscordBot (https://github.com/local/novamacrohub, 1.0) NovaMacroHub"


@dataclass
class SendResult:
    ok: bool
    error: str = ""
    retryable: bool = False   # safe to try again later
    message_id: str | None = None
    status: int | None = None


class FloodGuard:
    """Blocks more than `per_minute` messages to the same destination in 60 s."""

    def __init__(self, per_minute=10, clock=time.monotonic):
        self.per_minute = per_minute
        self.clock = clock
        self._hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self._lock = threading.Lock()

    def allow(self, dest: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits[dest]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def parse_webhook(url: str):
    m = WEBHOOK_RE.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def parse_channel_link(text: str):
    """'https://discord.com/channels/123/456' -> ('123', '456')."""
    m = CHANNEL_LINK_RE.search(text or "")
    return (m.group(1), m.group(2)) if m else None


def is_snowflake(text: str) -> bool:
    return bool(SNOWFLAKE_RE.match((text or "").strip()))


def make_nonce(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:25]


def friendly_error(status: int, body: dict | None, kind: str) -> str:
    code = (body or {}).get("code")
    msg = (body or {}).get("message", "")
    if status == 401:
        return "Discord rejected the bot token (401). Paste a fresh token in Discord Manager → Bot."
    if status == 403:
        if kind == "bot":
            return ("The bot is not allowed to post in this channel (403). In Discord, give the bot "
                    "'View Channel' and 'Send Messages' permission for this channel.")
        return "Discord refused the webhook (403)."
    if status == 404:
        if kind == "webhook":
            return "Webhook not found (404). It was probably deleted — create a new webhook and paste its URL."
        return "Channel not found (404). Check the channel ID, and make sure the bot is in that server."
    if status == 400:
        if code == 50006:
            return "The message is empty."
        if code == 50035:
            return f"Discord says the message is invalid: {msg}"
        return f"Discord rejected the message (400): {msg}"
    if status == 413:
        return "Message is too large."
    if status and status >= 500:
        return f"Discord is having problems right now ({status}). Will retry."
    return f"Discord error {status}: {msg}"


class DiscordClient:
    def __init__(self, session=None, flood_guard: FloodGuard | None = None, sleep=time.sleep,
                 max_retries=3, timeout=15):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.flood = flood_guard or FloodGuard()
        self.sleep = sleep
        self.max_retries = max_retries
        self.timeout = timeout
        self._buckets: dict[str, float] = {}  # route -> monotonic time when it resets
        self._global_until = 0.0
        self._lock = threading.Lock()

    # ---- public -------------------------------------------------------
    def send_webhook(self, url: str, content: str, allow_everyone=False, username=None) -> SendResult:
        if not parse_webhook(url):
            return SendResult(False, "That is not a valid Discord webhook URL.")
        err = self._validate(content)
        if err:
            return SendResult(False, err)
        payload = {"content": content, "allowed_mentions": self._mentions(allow_everyone)}
        if username:
            payload["username"] = username[:80]
        return self._post("webhook", url.split("?")[0] + "?wait=true", payload, headers={},
                          route=url.split("?")[0], dest=url, nonce_safe=False)

    def send_bot(self, token: str, channel_id: str, content: str, allow_everyone=False, nonce=None) -> SendResult:
        if not token:
            return SendResult(False, "No bot token saved. Add one in Discord Manager → Bot.")
        if not is_snowflake(channel_id):
            return SendResult(False, "Channel ID should be a long number like 123456789012345678.")
        err = self._validate(content)
        if err:
            return SendResult(False, err)
        payload = {"content": content, "allowed_mentions": self._mentions(allow_everyone)}
        if nonce:
            payload["nonce"] = nonce
            payload["enforce_nonce"] = True  # Discord drops a duplicate with the same nonce
        url = f"{API}/channels/{channel_id}/messages"
        return self._post("bot", url, payload, headers={"Authorization": f"Bot {token}"},
                          route=url, dest=channel_id, nonce_safe=bool(nonce))

    def bot_identity(self, token: str):
        r = self._get(f"{API}/users/@me", token)
        return r.json() if r is not None and r.status_code == 200 else self._raise(r)

    def bot_guilds(self, token: str):
        r = self._get(f"{API}/users/@me/guilds", token)
        return r.json() if r is not None and r.status_code == 200 else self._raise(r)

    def guild_text_channels(self, token: str, guild_id: str):
        r = self._get(f"{API}/guilds/{guild_id}/channels", token)
        if r is None or r.status_code != 200:
            self._raise(r)
        chans = [c for c in r.json() if c.get("type") in (0, 5)]  # text + announcement
        return sorted(chans, key=lambda c: (c.get("position", 0), c.get("name", "")))

    def channel_info(self, token: str, channel_id: str):
        r = self._get(f"{API}/channels/{channel_id}", token)
        return r.json() if r is not None and r.status_code == 200 else self._raise(r)

    def webhook_info(self, url: str):
        if not parse_webhook(url):
            raise ValueError("That is not a valid Discord webhook URL.")
        try:
            r = self.session.get(url.split("?")[0], timeout=self.timeout)
        except requests.RequestException as e:
            raise ConnectionError(f"Could not reach Discord: {e}") from e
        if r.status_code != 200:
            raise ValueError(friendly_error(r.status_code, _json(r), "webhook"))
        return r.json()

    # ---- internals ----------------------------------------------------
    @staticmethod
    def _mentions(allow_everyone):
        return {"parse": ["users", "roles", "everyone"] if allow_everyone else ["users", "roles"]}

    @staticmethod
    def _validate(content):
        if not content or not content.strip():
            return "The message is empty."
        if len(content) > MAX_LEN:
            return f"Message is {len(content)} characters; Discord's limit is {MAX_LEN}."
        return None

    def _get(self, url, token):
        try:
            return self.session.get(url, headers={"Authorization": f"Bot {token}"}, timeout=self.timeout)
        except requests.RequestException as e:
            raise ConnectionError(f"Could not reach Discord: {e}") from e

    def _raise(self, r):
        if r is None:
            raise ConnectionError("No response from Discord")
        raise ValueError(friendly_error(r.status_code, _json(r), "bot"))

    def _wait_for_bucket(self, route):
        with self._lock:
            until = max(self._buckets.get(route, 0.0), self._global_until)
        delay = until - time.monotonic()
        if delay > 0:
            self.sleep(min(delay, 60))

    def _note_headers(self, route, r):
        try:
            remaining = r.headers.get("X-RateLimit-Remaining")
            reset_after = r.headers.get("X-RateLimit-Reset-After")
            if remaining is not None and reset_after is not None and int(float(remaining)) <= 0:
                with self._lock:
                    self._buckets[route] = time.monotonic() + float(reset_after)
        except (TypeError, ValueError):
            pass

    def _post(self, kind, url, payload, headers, route, dest, nonce_safe) -> SendResult:
        if not self.flood.allow(dest):
            return SendResult(False, f"Flood protection: more than {self.flood.per_minute} messages to this "
                                     "channel in one minute were blocked. Change the limit in Settings if this is intended.")
        attempt = 0
        backoff = [2, 5, 10, 20]
        while True:
            attempt += 1
            self._wait_for_bucket(route)
            try:
                r = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            except requests.Timeout:
                # The message may or may not have arrived. Only retry when Discord
                # can de-duplicate it for us (bot messages with a nonce).
                if nonce_safe and attempt <= self.max_retries:
                    self.sleep(backoff[min(attempt - 1, 3)])
                    continue
                return SendResult(False, "Discord did not answer in time. The message may or may not have been "
                                         "sent, so it was not re-sent automatically (to avoid duplicates).")
            except requests.ConnectionError as e:
                # Connection never established -> nothing was sent; safe to retry.
                if attempt <= self.max_retries:
                    self.sleep(backoff[min(attempt - 1, 3)])
                    continue
                return SendResult(False, f"No internet connection to Discord ({e.__class__.__name__}).", retryable=True)
            except requests.RequestException as e:
                return SendResult(False, f"Could not send: {e}")

            self._note_headers(route, r)
            if r.status_code in (200, 201, 204):
                body = _json(r) or {}
                return SendResult(True, message_id=body.get("id"), status=r.status_code)
            if r.status_code == 429:
                body = _json(r) or {}
                retry_after = float(body.get("retry_after") or r.headers.get("Retry-After") or 1.0)
                if body.get("global"):
                    with self._lock:
                        self._global_until = time.monotonic() + retry_after
                if attempt <= self.max_retries + 2 and retry_after <= 120:
                    self.sleep(retry_after + 0.25)
                    continue
                return SendResult(False, f"Discord rate limit: try again in {retry_after:.0f}s.", retryable=True, status=429)
            safe_5xx = r.status_code >= 500 and (nonce_safe or r.status_code in (502, 503))
            if safe_5xx and attempt <= self.max_retries:
                self.sleep(backoff[min(attempt - 1, 3)])
                continue
            return SendResult(False, friendly_error(r.status_code, _json(r), kind),
                              retryable=safe_5xx, status=r.status_code)


def _json(r):
    try:
        return r.json()
    except Exception:
        return None
