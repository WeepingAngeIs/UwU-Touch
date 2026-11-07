"""Secure storage for the bot token and webhook URLs.

Uses Windows Credential Manager (through the `keyring` package). If that is not
available it falls back to Windows DPAPI encryption (tied to your Windows user
account) stored in a local file. Secrets are never written to the database or
to exported macro files.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
from pathlib import Path

SERVICE = "NovaMacroHub"


class SecretStore:
    def __init__(self, fallback_file: Path, use_keyring: bool = True):
        self.fallback_file = Path(fallback_file)
        self._lock = threading.Lock()
        self._keyring = None
        self.backend_name = "encrypted file"
        if use_keyring:
            try:
                import keyring
                from keyring.backends import fail
                kr = keyring.get_keyring()
                if not isinstance(kr, fail.Keyring):
                    self._keyring = keyring
                    self.backend_name = "Windows Credential Manager" if sys.platform == "win32" else type(kr).__name__
            except Exception:
                self._keyring = None

    # ---- public -------------------------------------------------------
    def get(self, key: str) -> str | None:
        if self._keyring:
            try:
                v = self._keyring.get_password(SERVICE, key)
                if v is not None:
                    return v
            except Exception:
                pass
        return self._file_get(key)

    def set(self, key: str, value: str):
        if self._keyring:
            try:
                self._keyring.set_password(SERVICE, key, value)
                self._file_delete(key)
                return
            except Exception:
                pass
        self._file_set(key, value)

    def delete(self, key: str):
        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE, key)
            except Exception:
                pass
        self._file_delete(key)

    # ---- fallback file ------------------------------------------------
    def _load(self) -> dict:
        if not self.fallback_file.exists():
            return {}
        try:
            return json.loads(self.fallback_file.read_text("utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict):
        self.fallback_file.write_text(json.dumps(data), "utf-8")

    def _file_get(self, key):
        with self._lock:
            blob = self._load().get(key)
        if not blob:
            return None
        try:
            return _unprotect(base64.b64decode(blob)).decode("utf-8")
        except Exception:
            return None

    def _file_set(self, key, value):
        with self._lock:
            data = self._load()
            data[key] = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
            self._save(data)

    def _file_delete(self, key):
        with self._lock:
            data = self._load()
            if key in data:
                del data[key]
                self._save(data)


# ---- Windows DPAPI ------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _to_blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _from_blob(blob) -> bytes:
        out = ctypes.string_at(blob.pbData, blob.cbData)
        ctypes.windll.kernel32.LocalFree(blob.pbData)
        return out

    def _protect(data: bytes) -> bytes:
        inp, _keep = _to_blob(data)
        out = _BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            raise OSError("CryptProtectData failed")
        return _from_blob(out)

    def _unprotect(data: bytes) -> bytes:
        inp, _keep = _to_blob(data)
        out = _BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
            raise OSError("CryptUnprotectData failed")
        return _from_blob(out)
else:  # development / tests on other systems: obfuscation only
    def _protect(data: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in data)

    def _unprotect(data: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in data)
