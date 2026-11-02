from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow

CREATOR = "Reda Benyassek"

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS V6")
    app.setOrganizationName(CREATOR)
    app.setApplicationDisplayName("JARVIS V6")
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = resource_root / "jarvis.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    cfg = __import__("core.config", fromlist=["load_config"]).load_config()
    mode = cfg.get("interface", {}).get("last_window_mode", "normal")
    if "--background" in sys.argv:
        window.showMinimized()
    else:
        window.apply_window_mode(mode)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
