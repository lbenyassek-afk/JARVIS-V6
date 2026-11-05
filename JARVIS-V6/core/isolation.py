from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class IsolationProfile:
    profile_id: str
    name: str
    available: bool
    executes: bool
    detail: str


def profiles() -> tuple[IsolationProfile, ...]:
    sandbox = sys.platform == "win32" and shutil.which("WindowsSandbox.exe") is not None
    return (
        IsolationProfile("host_reviewed", "Reviewed desktop", True, True,
                         "Allowlisted actions run on this desktop after permission checks."),
        IsolationProfile("dry_run", "Simulation", True, False,
                         "Plans are validated and displayed without executing desktop actions."),
        IsolationProfile("windows_sandbox", "Windows Sandbox", sandbox, False,
                         "Detected, but isolated mission execution is not connected yet." if sandbox
                         else "Windows Sandbox is unavailable on this system."),
    )


def selected(config: dict) -> IsolationProfile:
    wanted = str(config.get("desktop", {}).get("isolation_profile", "host_reviewed"))
    return next((item for item in profiles() if item.profile_id == wanted), profiles()[0])
