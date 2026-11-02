from __future__ import annotations

import re

import requests

from .config import load_config


CURRENT_VERSION = "6.0.0"


def _version(value: str) -> tuple[int, int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value))[:3]]
    return tuple((numbers + [0, 0, 0])[:3])


def check() -> dict:
    cfg = load_config().get("updates", {})
    repository = str(cfg.get("repository", "lbenyassek-afk/JARVIS-V6"))
    channel = str(cfg.get("channel", "stable"))
    url = f"https://api.github.com/repos/{repository}/releases"
    response = requests.get(url, timeout=(5, 12), headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    releases = response.json()
    candidates = [item for item in releases if not item.get("draft")]
    if channel == "stable":
        candidates = [item for item in candidates if not item.get("prerelease")]
    if not candidates:
        return {"available": False, "current": CURRENT_VERSION}
    latest = max(candidates, key=lambda item: _version(item.get("tag_name", "0")))
    latest_version = latest.get("tag_name", "0")
    return {
        "available": _version(latest_version) > _version(CURRENT_VERSION),
        "current": CURRENT_VERSION,
        "latest": latest_version,
        "url": latest.get("html_url", ""),
    }
