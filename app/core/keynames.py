"""Key naming shared by the recorder, the player and the hotkey system.

Keys are stored by a readable name ("w", "space", "ctrl_l", "f9") that maps to a
Windows virtual-key code. Recording by virtual key (not by typed character) means
Shift+1 is stored as "shift_l" + "1", which plays back exactly as it was pressed.
"""

VK_BY_NAME = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11,
    "alt": 0x12, "pause": 0x13, "caps_lock": 0x14, "esc": 0x1B, "space": 0x20,
    "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "print_screen": 0x2C, "insert": 0x2D, "delete": 0x2E,
    "cmd": 0x5B, "cmd_r": 0x5C, "menu": 0x5D,
    "num_0": 0x60, "num_1": 0x61, "num_2": 0x62, "num_3": 0x63, "num_4": 0x64,
    "num_5": 0x65, "num_6": 0x66, "num_7": 0x67, "num_8": 0x68, "num_9": 0x69,
    "num_multiply": 0x6A, "num_add": 0x6B, "num_subtract": 0x6D,
    "num_decimal": 0x6E, "num_divide": 0x6F,
    "num_lock": 0x90, "scroll_lock": 0x91,
    "shift_l": 0xA0, "shift_r": 0xA1, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt_l": 0xA4, "alt_r": 0xA5,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "media_play_pause": 0xB3, "media_next": 0xB0, "media_previous": 0xB1,
    "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_BY_NAME[_c] = ord(_c.upper())
for _d in "0123456789":
    VK_BY_NAME[_d] = ord(_d)
for _i in range(1, 25):
    VK_BY_NAME[f"f{_i}"] = 0x6F + _i

NAME_BY_VK = {}
for _name, _vk in VK_BY_NAME.items():
    NAME_BY_VK.setdefault(_vk, _name)
# Prefer the left/right specific names for modifiers when recording.
NAME_BY_VK[0x10] = "shift"
NAME_BY_VK[0x11] = "ctrl"
NAME_BY_VK[0x12] = "alt"

# Keys that need the "extended key" flag when sent as scan codes.
EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
    0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5, 0xB0, 0xB1, 0xB3, 0xAD, 0xAE, 0xAF,
}

PRETTY = {
    "space": "Space", "enter": "Enter", "esc": "Esc", "tab": "Tab",
    "backspace": "Backspace", "shift": "Shift", "shift_l": "Left Shift",
    "shift_r": "Right Shift", "ctrl": "Ctrl", "ctrl_l": "Left Ctrl",
    "ctrl_r": "Right Ctrl", "alt": "Alt", "alt_l": "Left Alt", "alt_r": "Right Alt",
    "cmd": "Windows", "caps_lock": "Caps Lock", "page_up": "Page Up",
    "page_down": "Page Down", "print_screen": "Print Screen",
}

MODIFIER_GROUP = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "win", "cmd_r": "win",
}


def vk_for(name: str) -> int:
    """Return the virtual-key code for a key name (supports 'vk_123')."""
    name = (name or "").lower()
    if name in VK_BY_NAME:
        return VK_BY_NAME[name]
    if name.startswith("vk_"):
        return int(name[3:])
    raise KeyError(f"Unknown key: {name}")


def name_for_vk(vk: int) -> str:
    return NAME_BY_VK.get(vk, f"vk_{vk}")


def pretty(name: str) -> str:
    if name in PRETTY:
        return PRETTY[name]
    if len(name) == 1:
        return name.upper()
    if name.startswith("f") and name[1:].isdigit():
        return name.upper()
    return name.replace("_", " ").title()


def is_known(name: str) -> bool:
    try:
        vk_for(name)
        return True
    except (KeyError, ValueError):
        return False


def parse_hotkey(text: str):
    """'ctrl+shift+f9' -> (frozenset({'ctrl','shift'}), 'f9'). Raises ValueError."""
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")
    mods, main = set(), None
    for p in parts:
        if p in ("ctrl", "shift", "alt", "win"):
            mods.add(p)
        else:
            if main is not None:
                raise ValueError("A hotkey can only have one main key")
            if not is_known(p):
                raise ValueError(f"Unknown key '{p}'")
            main = p
    if main is None:
        raise ValueError("Hotkey needs a main key (not only Ctrl/Shift/Alt)")
    return frozenset(mods), main


def hotkey_label(text: str) -> str:
    try:
        mods, main = parse_hotkey(text)
    except ValueError:
        return text or "(none)"
    order = [m for m in ("ctrl", "shift", "alt", "win") if m in mods]
    return " + ".join([m.title() for m in order] + [pretty(main)])
