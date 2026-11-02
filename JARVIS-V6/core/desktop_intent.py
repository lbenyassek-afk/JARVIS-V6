from __future__ import annotations

import re

from .tasks import Step


APPLICATIONS = {
    "notepad": "Notepad",
    "calculator": "Calculator",
    "file explorer": "File Explorer",
    "explorer": "File Explorer",
    "paint": "Paint",
    "task manager": "Task Manager",
    "settings": "Windows Settings",
    "windows settings": "Windows Settings",
    "browser": "Default Browser",
    "snipping tool": "Snipping Tool",
}

DIRECT_COMMANDS = {
    "show desktop": Step("shortcut", "Show desktop"),
    "switch window": Step("shortcut", "Switch window"),
    "volume up": Step("media_key", "volumeup"),
    "volume down": Step("media_key", "volumedown"),
    "mute": Step("media_key", "volumemute"),
    "mute volume": Step("media_key", "volumemute"),
    "play pause": Step("media_key", "playpause"),
    "pause music": Step("media_key", "playpause"),
    "next track": Step("media_key", "nexttrack"),
    "previous track": Step("media_key", "prevtrack"),
    "take a screenshot": Step("screenshot", ""),
    "take screenshot": Step("screenshot", ""),
    "scroll up": Step("scroll", "5"),
    "scroll down": Step("scroll", "-5"),
}


def parse(text: str):
    """Return a bounded desktop goal and steps, or None for normal chat."""
    clean = " ".join(str(text).casefold().strip().split())
    clean = re.sub(r"^(?:please|jarvis|hey jarvis)\s+", "", clean)
    clean = clean.rstrip(".!?")
    direct = DIRECT_COMMANDS.get(clean)
    if direct:
        return (clean.title(), [Step(direct.action, direct.value)])
    match = re.fullmatch(r"(?:open|launch|start)\s+(?:the\s+)?(.+?)(?:\s+app)?", clean)
    if match and match.group(1) in APPLICATIONS:
        application = APPLICATIONS[match.group(1)]
        return (f"Open {application}", [Step("open_app", application)])
    return None
