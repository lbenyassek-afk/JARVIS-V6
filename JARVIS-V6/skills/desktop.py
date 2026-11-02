from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


APPS = {
    "Notepad": ("exe", "notepad.exe"),
    "Calculator": ("exe", "calc.exe"),
    "File Explorer": ("exe", "explorer.exe"),
    "Paint": ("exe", "mspaint.exe"),
    "Windows Settings": ("uri", "ms-settings:"),
    "Default Browser": ("uri", "https://www.google.com"),
}
SHORTCUTS = {
    "Copy": ("ctrl", "c"), "Paste": ("ctrl", "v"),
    "Select all": ("ctrl", "a"), "Save": ("ctrl", "s"),
    "Undo": ("ctrl", "z"), "Redo": ("ctrl", "y"),
    "Switch window": ("alt", "tab"), "Show desktop": ("win", "d"),
}
KEYS = ("enter", "tab", "escape", "up", "down", "left", "right", "backspace", "delete")
MEDIA_KEYS = ("volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack")


def open_app(value: str) -> str:
    if value not in APPS:
        raise ValueError("Application is not approved")
    kind, target = APPS[value]
    if kind == "uri":
        os.startfile(target)
    else:
        subprocess.Popen([target], shell=False)
    return f"Opened {value}."


def type_text(value: str) -> str:
    if len(value) > 4000:
        raise ValueError("Typed text is limited to 4,000 characters")
    import pyautogui
    pyautogui.write(value, interval=0.008)
    return f"Typed {len(value)} characters into the focused application."


def copy_text(value: str) -> str:
    if len(value) > 20_000:
        raise ValueError("Clipboard text is limited to 20,000 characters")
    import pyperclip
    pyperclip.copy(value)
    return f"Copied {len(value)} characters to the clipboard."


def shortcut(value: str) -> str:
    if value not in SHORTCUTS:
        raise ValueError("Shortcut is not approved")
    import pyautogui
    pyautogui.hotkey(*SHORTCUTS[value])
    return f"Pressed {value}."


def press_key(value: str) -> str:
    if value not in KEYS:
        raise ValueError("Key is not approved")
    import pyautogui
    pyautogui.press(value)
    return f"Pressed {value}."


def click_point(value: str) -> str:
    match = re.fullmatch(r"\s*(\d{1,5})\s*,\s*(\d{1,5})\s*", value)
    if not match:
        raise ValueError("Click coordinates must use x,y, for example 640,360")
    import pyautogui
    x, y = int(match.group(1)), int(match.group(2))
    width, height = pyautogui.size()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("Click coordinates are outside the current screen")
    pyautogui.click(x, y)
    return f"Clicked screen position {x},{y}."


def scroll(value: str) -> str:
    amount = int(value)
    if not -20 <= amount <= 20 or amount == 0:
        raise ValueError("Scroll amount must be between -20 and 20, excluding zero")
    import pyautogui
    pyautogui.scroll(amount)
    return f"Scrolled {amount} steps."


def media_key(value: str) -> str:
    if value not in MEDIA_KEYS:
        raise ValueError("Media key is not approved")
    import pyautogui
    pyautogui.press(value)
    return f"Pressed media control {value}."


def screenshot(_value: str) -> str:
    import pyautogui
    folder = Path.home() / "Pictures" / "JARVIS Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"JARVIS-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    pyautogui.screenshot(str(path))
    return f"Saved screenshot to {path}."


def wait(value: str) -> str:
    seconds = max(0.1, min(float(value), 15.0))
    time.sleep(seconds)
    return f"Waited {seconds:g} seconds."


SKILL = {
    "name": "desktop",
    "version": 1,
    "actions": [
        {"name": "open_app", "label": "Open approved application", "description": "Launch a known Windows application.", "handler": open_app, "values": tuple(APPS)},
        {"name": "type_text", "label": "Type text", "description": "Type into the currently focused application.", "handler": type_text, "sensitive": True},
        {"name": "copy_text", "label": "Copy text", "description": "Put text on the clipboard.", "handler": copy_text},
        {"name": "shortcut", "label": "Keyboard shortcut", "description": "Run a fixed approved keyboard shortcut.", "handler": shortcut, "values": tuple(SHORTCUTS), "sensitive": True},
        {"name": "press_key", "label": "Press approved key", "description": "Press one navigation/editing key.", "handler": press_key, "values": KEYS, "sensitive": True},
        {"name": "click_point", "label": "Click screen position", "description": "Click reviewed x,y screen coordinates.", "handler": click_point, "sensitive": True},
        {"name": "scroll", "label": "Scroll active window", "description": "Scroll by -20 to 20 steps.", "handler": scroll, "sensitive": True},
        {"name": "media_key", "label": "Media or volume control", "description": "Use an approved media key.", "handler": media_key, "values": MEDIA_KEYS},
        {"name": "screenshot", "label": "Save screenshot", "description": "Save the desktop to Pictures/JARVIS Screenshots.", "handler": screenshot, "sensitive": True},
        {"name": "wait", "label": "Wait", "description": "Pause between desktop steps for at most 15 seconds.", "handler": wait},
    ],
}
