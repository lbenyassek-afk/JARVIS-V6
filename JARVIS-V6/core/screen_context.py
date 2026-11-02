from __future__ import annotations

import ctypes
import sys


def snapshot() -> dict:
    """Return transient desktop metadata. No screenshot is written to disk."""
    title = "Desktop"
    if sys.platform == "win32":
        try:
            handle = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(handle)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(handle, buffer, length + 1)
            title = buffer.value.strip() or title
        except Exception:
            pass
    try:
        import pyautogui
        size = pyautogui.size()
        dimensions = f"{size.width} × {size.height}"
    except Exception:
        dimensions = "Unavailable"
    return {"active_window": title[:160], "display": dimensions}
