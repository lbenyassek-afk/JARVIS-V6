from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from core.windows_automation import (
    focus_window, inspect_active_app, invoke_control, set_control_text, validate_control_name,
    validate_target_text, window_layout, verify_control_text, verify_focused_window,
    verify_window_layout,
)
from core.verification import VerificationResult


APPS = {
    "Notepad": ("exe", "notepad.exe"),
    "Calculator": ("exe", "calc.exe"),
    "File Explorer": ("exe", "explorer.exe"),
    "Paint": ("exe", "mspaint.exe"),
    "Task Manager": ("exe", "taskmgr.exe"),
    "Snipping Tool": ("uri", "ms-screenclip:"),
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
    import pyperclip
    # Clipboard paste is much faster than key-by-key typing and preserves
    # accents, symbols and non-English text. Restore the previous clipboard.
    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(value)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(.08)
    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
    return f"Typed {len(value)} characters into the focused application."


def copy_text(value: str) -> str:
    if len(value) > 20_000:
        raise ValueError("Clipboard text is limited to 20,000 characters")
    import pyperclip
    pyperclip.copy(value)
    return f"Copied {len(value)} characters to the clipboard."


def verify_clipboard(value: str, _result: str) -> VerificationResult:
    import pyperclip
    matched = pyperclip.paste() == value
    return VerificationResult(matched, "Clipboard content matched" if matched else "Clipboard content did not match")


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


def _pointer_position(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{1,5})\s*,\s*(\d{1,5})\s*", value)
    if not match:
        raise ValueError("Coordinates must use x,y, for example 640,360")
    import pyautogui
    x, y = int(match.group(1)), int(match.group(2))
    width, height = pyautogui.size()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("Coordinates are outside the current screen")
    return x, y


def move_pointer(value: str) -> str:
    import pyautogui
    x, y = _pointer_position(value)
    pyautogui.moveTo(x, y, duration=.18)
    return f"Moved pointer to {x},{y}."


def verify_pointer(value: str, _result: str) -> VerificationResult:
    import pyautogui
    expected = _pointer_position(value)
    actual = tuple(pyautogui.position())
    matched = abs(actual[0] - expected[0]) <= 2 and abs(actual[1] - expected[1]) <= 2
    return VerificationResult(matched, f"Pointer observed at {actual[0]},{actual[1]}")


def double_click(value: str) -> str:
    import pyautogui
    x, y = _pointer_position(value)
    pyautogui.doubleClick(x, y, interval=.12)
    return f"Double-clicked screen position {x},{y}."


def right_click(value: str) -> str:
    import pyautogui
    x, y = _pointer_position(value)
    pyautogui.rightClick(x, y)
    return f"Right-clicked screen position {x},{y}."


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


def verify_screenshot(_value: str, result: str) -> VerificationResult:
    prefix = "Saved screenshot to "
    raw = str(result).removeprefix(prefix).removesuffix(".")
    exists = bool(raw) and Path(raw).is_file()
    return VerificationResult(exists, "Screenshot file exists" if exists else "Screenshot file was not found")


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
        {"name": "copy_text", "label": "Copy text", "description": "Put text on the clipboard.", "handler": copy_text,
         "verifier": verify_clipboard, "retry_safe": True},
        {"name": "shortcut", "label": "Keyboard shortcut", "description": "Run a fixed approved keyboard shortcut.", "handler": shortcut, "values": tuple(SHORTCUTS), "sensitive": True},
        {"name": "press_key", "label": "Press approved key", "description": "Press one navigation/editing key.", "handler": press_key, "values": KEYS, "sensitive": True},
        {"name": "click_point", "label": "Click screen position", "description": "Click reviewed x,y screen coordinates.", "handler": click_point, "sensitive": True},
        {"name": "move_pointer", "label": "Move pointer", "description": "Move to reviewed x,y screen coordinates without clicking.", "handler": move_pointer, "sensitive": True,
         "verifier": verify_pointer, "retry_safe": True},
        {"name": "double_click", "label": "Double-click screen position", "description": "Double-click reviewed x,y screen coordinates.", "handler": double_click, "sensitive": True},
        {"name": "right_click", "label": "Right-click screen position", "description": "Right-click reviewed x,y screen coordinates.", "handler": right_click, "sensitive": True},
        {"name": "scroll", "label": "Scroll active window", "description": "Scroll by -20 to 20 steps.", "handler": scroll, "sensitive": True},
        {"name": "media_key", "label": "Media or volume control", "description": "Use an approved media key.", "handler": media_key, "values": MEDIA_KEYS},
        {"name": "screenshot", "label": "Save screenshot", "description": "Save the desktop to Pictures/JARVIS Screenshots.", "handler": screenshot, "sensitive": True,
         "verifier": verify_screenshot},
        {"name": "wait", "label": "Wait", "description": "Pause between desktop steps for at most 15 seconds.", "handler": wait},
        {"name": "inspect_active_app", "label": "Inspect active application", "description": "Read named Windows accessibility controls from the active application without taking a screenshot.", "handler": inspect_active_app, "read_only": True},
        {"name": "focus_window", "label": "Focus open window", "description": "Focus one open window by a reviewed title fragment.", "handler": focus_window, "sensitive": True, "validator": validate_control_name,
         "verifier": verify_focused_window, "retry_safe": True},
        {"name": "invoke_control", "label": "Activate named control", "description": "Activate one reviewed button, menu item or link by its accessible name.", "handler": invoke_control, "sensitive": True, "validator": validate_control_name},
        {"name": "set_control_text", "label": "Enter text in named field", "description": "Set a reviewed text field using Control name || text.", "handler": set_control_text, "sensitive": True, "validator": validate_target_text,
         "verifier": verify_control_text, "retry_safe": True},
        {"name": "window_layout", "label": "Change active window layout", "description": "Minimize, maximize or restore the active window.", "handler": window_layout, "values": ("Minimize", "Maximize", "Restore"),
         "verifier": verify_window_layout, "retry_safe": True},
    ],
}
