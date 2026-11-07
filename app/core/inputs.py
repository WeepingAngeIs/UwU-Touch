"""Keyboard/mouse output drivers used by playback.

WindowsDriver sends input with the Win32 SendInput API. In "scancode" mode keys
are sent as hardware scan codes, which most games (including DirectInput games)
accept. "virtualkey" mode is the standard Windows way and works better in some
normal desktop apps.
"""
from __future__ import annotations

import sys
import time

from . import keynames


class BaseDriver:
    """Tracks what is held down so everything can be released on stop."""

    def __init__(self):
        self.held_keys: set[str] = set()
        self.held_buttons: set[str] = set()

    # subclasses implement the _raw_* methods
    def key_down(self, key):
        self._raw_key(key, True)
        self.held_keys.add(key)

    def key_up(self, key):
        self._raw_key(key, False)
        self.held_keys.discard(key)

    def mouse_move(self, x, y):
        self._raw_move(int(x), int(y))

    def mouse_button(self, button, down, x=None, y=None):
        if x is not None and y is not None:
            self._raw_move(int(x), int(y))
        self._raw_button(button, down)
        if down:
            self.held_buttons.add(button)
        else:
            self.held_buttons.discard(button)

    def scroll(self, x, y, dx, dy):
        if x is not None and y is not None:
            self._raw_move(int(x), int(y))
        self._raw_scroll(int(dx), int(dy))

    def type_text(self, text, interval=0.01, should_stop=lambda: False):
        for ch in text:
            if should_stop():
                return
            if ch == "\n":
                self._raw_key("enter", True)
                self._raw_key("enter", False)
            else:
                self._raw_char(ch)
            time.sleep(interval)

    def release_all(self):
        """Release every key and button that playback is still holding."""
        for k in list(self.held_keys):
            try:
                self._raw_key(k, False)
            except Exception:
                pass
        self.held_keys.clear()
        for b in list(self.held_buttons):
            try:
                self._raw_button(b, False)
            except Exception:
                pass
        self.held_buttons.clear()

    def _raw_key(self, key, down): raise NotImplementedError
    def _raw_move(self, x, y): raise NotImplementedError
    def _raw_button(self, button, down): raise NotImplementedError
    def _raw_scroll(self, dx, dy): raise NotImplementedError
    def _raw_char(self, ch): raise NotImplementedError


class FakeDriver(BaseDriver):
    """Records calls instead of sending input. Used by tests."""

    def __init__(self):
        super().__init__()
        self.events = []
        self.t0 = time.perf_counter()

    def _log(self, *ev):
        self.events.append((time.perf_counter() - self.t0,) + ev)

    def _raw_key(self, key, down): self._log("key", key, down)
    def _raw_move(self, x, y): self._log("move", x, y)
    def _raw_button(self, button, down): self._log("button", button, down)
    def _raw_scroll(self, dx, dy): self._log("scroll", dx, dy)
    def _raw_char(self, ch): self._log("char", ch)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x4, 0x8
    MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x01000
    BUTTON_FLAGS = {
        "left": (0x0002, 0x0004, 0), "right": (0x0008, 0x0010, 0), "middle": (0x0020, 0x0040, 0),
        "x1": (0x0080, 0x0100, 1), "x2": (0x0080, 0x0100, 2),
    }

    class WindowsDriver(BaseDriver):
        def __init__(self, mode="scancode"):
            super().__init__()
            self.mode = mode

        def _send(self, *inputs):
            arr = (INPUT * len(inputs))(*inputs)
            sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
            if sent != len(inputs):
                err = ctypes.get_last_error()
                raise OSError(f"Windows blocked the input (SendInput error {err}). "
                              "If the game runs as Administrator, run Nova Macro Hub as Administrator too.")

        def _raw_key(self, key, down):
            vk = keynames.vk_for(key)
            flags = 0 if down else KEYEVENTF_KEYUP
            if vk in keynames.EXTENDED_VKS:
                flags |= KEYEVENTF_EXTENDEDKEY
            if self.mode == "scancode":
                scan = user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
                if scan:
                    ki = KEYBDINPUT(0, scan, flags | KEYEVENTF_SCANCODE, 0, 0)
                else:
                    ki = KEYBDINPUT(vk, 0, flags, 0, 0)
            else:
                ki = KEYBDINPUT(vk, 0, flags, 0, 0)
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = ki
            self._send(inp)

        def _abs(self, x, y):
            vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            vw, vh = max(user32.GetSystemMetrics(78), 2), max(user32.GetSystemMetrics(79), 2)
            nx = int(round((x - vx) * 65535 / (vw - 1)))
            ny = int(round((y - vy) * 65535 / (vh - 1)))
            return max(0, min(65535, nx)), max(0, min(65535, ny))

        def _raw_move(self, x, y):
            nx, ny = self._abs(x, y)
            inp = INPUT(type=INPUT_MOUSE)
            inp.u.mi = MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
            self._send(inp)
            user32.SetCursorPos(int(x), int(y))  # exact pixel even with odd DPI rounding

        def _raw_button(self, button, down):
            dn, up, data = BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])
            inp = INPUT(type=INPUT_MOUSE)
            inp.u.mi = MOUSEINPUT(0, 0, data, dn if down else up, 0, 0)
            self._send(inp)

        def _raw_scroll(self, dx, dy):
            if dy:
                inp = INPUT(type=INPUT_MOUSE)
                inp.u.mi = MOUSEINPUT(0, 0, (dy * 120) & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, 0)
                self._send(inp)
            if dx:
                inp = INPUT(type=INPUT_MOUSE)
                inp.u.mi = MOUSEINPUT(0, 0, (dx * 120) & 0xFFFFFFFF, MOUSEEVENTF_HWHEEL, 0, 0)
                self._send(inp)

        def _raw_char(self, ch):
            data = ch.encode("utf-16-le")
            units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
            for u in units:
                for up in (False, True):
                    inp = INPUT(type=INPUT_KEYBOARD)
                    inp.u.ki = KEYBDINPUT(0, u, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
                    self._send(inp)


class PynputDriver(BaseDriver):
    """Fallback for non-Windows systems (development only)."""

    def __init__(self, mode="virtualkey"):
        super().__init__()
        from pynput import keyboard, mouse
        self._kb = keyboard.Controller()
        self._ms = mouse.Controller()
        self._keyboard = keyboard
        self._mouse = mouse

    def _key_obj(self, key):
        k = self._keyboard.Key
        special = {"ctrl_l": k.ctrl_l, "ctrl_r": k.ctrl_r, "ctrl": k.ctrl, "shift": k.shift,
                   "shift_l": k.shift_l, "shift_r": k.shift_r, "alt": k.alt, "alt_l": k.alt_l,
                   "alt_r": k.alt_r, "esc": k.esc, "page_up": k.page_up, "page_down": k.page_down}
        if key in special:
            return special[key]
        if hasattr(k, key):
            return getattr(k, key)
        if len(key) == 1:
            return key
        return self._keyboard.KeyCode.from_vk(keynames.vk_for(key))

    def _raw_key(self, key, down):
        obj = self._key_obj(key)
        (self._kb.press if down else self._kb.release)(obj)

    def _raw_move(self, x, y):
        self._ms.position = (x, y)

    def _raw_button(self, button, down):
        b = getattr(self._mouse.Button, button, self._mouse.Button.left)
        (self._ms.press if down else self._ms.release)(b)

    def _raw_scroll(self, dx, dy):
        self._ms.scroll(dx, dy)

    def _raw_char(self, ch):
        self._kb.type(ch)


def make_driver(mode="scancode") -> BaseDriver:
    if sys.platform == "win32":
        return WindowsDriver(mode)
    return PynputDriver(mode)
