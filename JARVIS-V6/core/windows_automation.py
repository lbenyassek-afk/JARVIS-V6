from __future__ import annotations

import ctypes
import re
import sys

from .verification import VerificationResult


SEPARATOR = "||"


def split_target_text(value: str) -> tuple[str, str]:
    parts = str(value).split(SEPARATOR, 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("Use Control name || text")
    target, text = parts[0].strip(), parts[1].strip()
    if len(target) > 160 or len(text) > 4000:
        raise ValueError("Control names are limited to 160 characters and text to 4,000 characters")
    return target, text


def validate_control_name(value: str) -> str:
    value = " ".join(str(value).split())
    if not value or len(value) > 160:
        raise ValueError("Provide a visible control or window name up to 160 characters")
    return value


def validate_target_text(value: str) -> str:
    target, text = split_target_text(value)
    return target + " || " + text


def _require_windows():
    if sys.platform != "win32":
        raise RuntimeError("App-aware control is available on Windows only")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("Windows app-awareness is not installed. Reinstall JARVIS V6.") from exc
    return Desktop(backend="uia")


def _active_window():
    desktop = _require_windows()
    handle = ctypes.windll.user32.GetForegroundWindow()
    if not handle:
        raise RuntimeError("No active application window was found")
    return desktop.window(handle=handle)


def active_window_title() -> str:
    window = _active_window()
    return " ".join(str(window.window_text() or "").split())


def _control_rows(window=None, limit: int = 80) -> list[dict]:
    window = window or _active_window()
    rows, seen = [], set()
    for control in window.descendants():
        try:
            name = " ".join(str(control.window_text() or "").split())
            kind = str(control.element_info.control_type or "Control")
            if not name or not control.is_visible():
                continue
            key = (name.casefold(), kind.casefold())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name[:160], "type": kind[:60], "enabled": bool(control.is_enabled())})
            if len(rows) >= max(1, min(int(limit), 120)):
                break
        except Exception:
            continue
    return rows


def active_controls(limit: int = 80) -> list[dict]:
    return _control_rows(limit=limit)


def inspect_active_app(_value: str = "") -> str:
    window = _active_window()
    title = " ".join(str(window.window_text() or "Active application").split())
    rows = _control_rows(window, 40)
    if not rows:
        return f"{title}: no named accessibility controls were exposed."
    summary = ", ".join(f"{row['name']} [{row['type']}]" for row in rows)
    return f"{title}: {summary}"


def _matching_controls(target: str):
    target = " ".join(str(target).casefold().split())
    if not target or len(target) > 160:
        raise ValueError("Provide a visible control name")
    window = _active_window()
    candidates = []
    for control in window.descendants():
        try:
            name = " ".join(str(control.window_text() or "").split())
            if name and control.is_visible() and control.is_enabled():
                candidates.append((name, control))
        except Exception:
            continue
    exact = [(name, control) for name, control in candidates if name.casefold() == target]
    matches = exact or [(name, control) for name, control in candidates if target in name.casefold()]
    if not matches:
        visible = ", ".join(name for name, _control in candidates[:12])
        raise ValueError(f"No visible control matched '{target}'. Visible controls: {visible or 'none'}")
    unique_names = list(dict.fromkeys(name for name, _control in matches))
    if len(matches) > 1:
        raise ValueError("Several controls matched. Be more specific: " + ", ".join(unique_names[:8]))
    return matches[0]


def invoke_control(value: str) -> str:
    name, control = _matching_controls(value)
    try:
        control.invoke()
    except Exception:
        control.click_input()
    return f"Activated '{name}' in the active application."


def set_control_text(value: str) -> str:
    target, text = split_target_text(value)
    name, control = _matching_controls(target)
    try:
        control.set_edit_text(text)
    except Exception:
        import pyautogui
        import pyperclip
        control.click_input()
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
    return f"Entered {len(text)} characters into '{name}'."


def focus_window(value: str) -> str:
    query = " ".join(str(value).casefold().split())
    if not query or len(query) > 160:
        raise ValueError("Provide part of an open window title")
    desktop = _require_windows()
    matches = []
    for window in desktop.windows():
        try:
            title = " ".join(str(window.window_text() or "").split())
            if title and query in title.casefold() and window.is_visible():
                matches.append((title, window))
        except Exception:
            continue
    exact = [(title, window) for title, window in matches if title.casefold() == query]
    matches = exact or matches
    if not matches:
        raise ValueError(f"No open window matched '{value}'")
    if len(matches) > 1:
        raise ValueError("Several windows matched: " + ", ".join(title for title, _ in matches[:8]))
    title, window = matches[0]
    window.set_focus()
    return f"Focused '{title}'."


def verify_focused_window(value: str, _result: str) -> VerificationResult:
    title = active_window_title()
    matched = str(value).casefold().strip() in title.casefold()
    return VerificationResult(matched, f"Active window observed as '{title or 'unknown'}'")


def window_layout(value: str) -> str:
    action = str(value).casefold().strip()
    if action not in ("minimize", "maximize", "restore"):
        raise ValueError("Window layout must be Minimize, Maximize or Restore")
    window = _active_window()
    getattr(window, action)()
    return f"{action.title()}d the active window."


def verify_window_layout(value: str, _result: str) -> VerificationResult:
    action = str(value).casefold().strip()
    window = _active_window()
    if action == "minimize":
        matched = bool(window.is_minimized())
    elif action == "maximize":
        matched = bool(window.is_maximized())
    else:
        matched = not window.is_minimized() and not window.is_maximized()
    return VerificationResult(matched, f"Window layout observed as {action}")


def verify_control_text(value: str, _result: str) -> VerificationResult:
    target, expected = split_target_text(value)
    name, control = _matching_controls(target)
    candidates = []
    for reader in (lambda: control.get_value(), lambda: control.window_text()):
        try:
            candidates.append(str(reader()))
        except Exception:
            pass
    matched = expected in candidates or any(expected == item for item in candidates)
    return VerificationResult(matched, f"Read back text from '{name}'" if matched
                              else f"Could not confirm text in '{name}'")
