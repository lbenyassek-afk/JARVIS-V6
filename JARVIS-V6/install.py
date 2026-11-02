from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BUILD_ROOT = (
    Path(os.environ["LOCALAPPDATA"]) / "JARVIS-V6-Build"
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA")
    else ROOT / ".build"
)
VENV = BUILD_ROOT / "venv"
DIST_DIR = BUILD_ROOT / "dist"
WORK_DIR = BUILD_ROOT / "work"
SPEC_DIR = BUILD_ROOT / "spec"


def run(*args: str) -> None:
    print("\n>", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def create_shortcut(target: Path, arguments: str = "") -> None:
    ps = (
        "$desktop=[Environment]::GetFolderPath('Desktop');"
        "if([string]::IsNullOrWhiteSpace($desktop)){"
        "$desktop=Join-Path $env:USERPROFILE 'Desktop'};"
        "New-Item -ItemType Directory -Force -Path $desktop | Out-Null;"
        "$w=New-Object -ComObject WScript.Shell;"
        "$locations=@($desktop,[Environment]::GetFolderPath('Programs'));"
        "foreach($location in $locations){"
        "if(-not [string]::IsNullOrWhiteSpace($location)){"
        "New-Item -ItemType Directory -Force -Path $location | Out-Null;"
        "$shortcut=Join-Path $location 'JARVIS V6.lnk';"
        "$s=$w.CreateShortcut($shortcut);"
        f"$s.TargetPath='{str(target).replace("'", "''")}';"
        f"$s.Arguments='{arguments.replace("'", "''")}';"
        f"$s.WorkingDirectory='{str(target.parent).replace("'", "''")}';"
        "$s.Description='JARVIS V6 Personal Intelligence — Created by Reda Benyassek';"
        f"$s.IconLocation='{str(target).replace("'", "''")},0';"
        "$s.Save()}};"
        "$startup=[Environment]::GetFolderPath('Startup');"
        "if(-not [string]::IsNullOrWhiteSpace($startup)){"
        "$shortcut=Join-Path $startup 'JARVIS V6.lnk';"
        "$s=$w.CreateShortcut($shortcut);"
        f"$s.TargetPath='{str(target).replace("'", "''")}';"
        "$s.Arguments='--background';"
        f"$s.WorkingDirectory='{str(target.parent).replace("'", "''")}';"
        "$s.Description='JARVIS V6 background startup';"
        f"$s.IconLocation='{str(target).replace("'", "''")},0';"
        "$s.Save()}"
    )
    run("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)
    print("\nJARVIS V6 Desktop, Start Menu and Windows startup shortcuts created.")


def installed_application() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "JARVIS V6"
    return base / "JARVIS V6.exe"


def install_built_application(built_executable: Path) -> Path:
    destination = installed_application().parent
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(built_executable.parent, destination)
    executable = destination / "JARVIS V6.exe"
    if not executable.exists():
        raise RuntimeError("Windows application installation did not produce JARVIS V6.exe.")
    return executable


def build_application(python: Path) -> Path:
    separator = ";" if sys.platform == "win32" else ":"
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    run(
        str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "JARVIS V6", "--icon", str(ROOT / "jarvis.ico"),
        "--version-file", str(ROOT / "version_info.txt"),
        "--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR),
        "--specpath", str(SPEC_DIR),
        "--add-data", f"{ROOT / 'core' / 'prompt.txt'}{separator}core",
        "--add-data", f"{ROOT / 'core' / 'manager_prompt.txt'}{separator}core",
        "--add-data", f"{ROOT / 'jarvis.ico'}{separator}.",
        "--add-data", f"{ROOT / 'skills'}{separator}skills",
        "--hidden-import", "PyQt6.QtTextToSpeech",
        "--hidden-import", "PyQt6.QtMultimedia", "--collect-all", "edge_tts",
        "--collect-all", "speech_recognition", "--collect-all", "pocketsphinx",
        "--collect-all", "sounddevice", "--hidden-import", "numpy",
        "--hidden-import", "pyautogui", "--hidden-import", "pyperclip",
        "--collect-all", "keyring", str(ROOT / "main.py"),
    )
    executable = DIST_DIR / "JARVIS V6" / ("JARVIS V6.exe" if sys.platform == "win32" else "JARVIS V6")
    if not executable.exists():
        raise RuntimeError("Application build finished without producing the executable.")
    return executable


def main() -> None:
    if sys.platform != "win32":
        print("This installer creates a Windows desktop application shortcut.")
    existing_executable = installed_application()
    if "--shortcut-only" in sys.argv:
        if not existing_executable.exists():
            existing_executable = DIST_DIR / "JARVIS V6" / "JARVIS V6.exe"
        if not existing_executable.exists():
            raise FileNotFoundError("JARVIS V6.exe is missing. Run install.bat first.")
        create_shortcut(existing_executable)
        print("\nShortcut repaired. Open JARVIS V6 from your Desktop.")
        return
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"\nUsing short build directory: {BUILD_ROOT}")
    if not VENV.exists():
        run(sys.executable, "-m", "venv", str(VENV))
    python = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run(str(python), "-m", "pip", "install", "--upgrade", "pip")
    run(str(python), "-m", "pip", "install", "-r", "requirements.txt")
    if sys.platform == "win32":
        print("\nBuilding the native Windows application. This can take several minutes…")
        executable = install_built_application(build_application(python))
        create_shortcut(executable)
    print("\nJARVIS V6 installation complete.")
    print("Double-click 'JARVIS V6' on your Desktop.")
    print("Created by Reda Benyassek.")


if __name__ == "__main__":
    main()
