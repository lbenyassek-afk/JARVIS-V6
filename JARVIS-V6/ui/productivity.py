from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from core import backup
from core.audit import recent as recent_actions
from core.config import load_config, save_config
from core.health import run as run_health
from core.metrics import snapshot as metric_snapshot
from core.benchmarks import run_suite as run_benchmarks
from core.workspace import delete as delete_record
from core.workspace import records, save


class CommandPalette(QDialog):
    def __init__(self, actions: dict[str, callable], parent=None):
        super().__init__(parent); self.actions = actions
        self.setWindowTitle("JARVIS V6 // COMMAND PALETTE"); self.resize(560, 520)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search commands…")
        self.list = QListWidget(); layout.addWidget(self.search); layout.addWidget(self.list, 1)
        self.search.textChanged.connect(self.refresh); self.search.returnPressed.connect(self.run_selected)
        self.list.itemDoubleClicked.connect(lambda _item: self.run_selected())
        self.refresh(); self.search.setFocus()

    def refresh(self):
        query = self.search.text().casefold().strip(); self.list.clear()
        for name in self.actions:
            if not query or query in name.casefold(): self.list.addItem(name)
        if self.list.count(): self.list.setCurrentRow(0)

    def run_selected(self):
        item = self.list.currentItem()
        if not item: return
        callback = self.actions.get(item.text()); self.accept()
        if callback: QTimer.singleShot(0, callback)


class DiagnosticsDialog(QDialog):
    def __init__(self, registry, parent=None):
        super().__init__(parent); self.registry = registry
        self.setWindowTitle("JARVIS V6 // SYSTEM DIAGNOSTICS"); self.resize(720, 520)
        layout = QVBoxLayout(self)
        title = QLabel("FIRST-RUN AND SYSTEM HEALTH"); title.setObjectName("section"); layout.addWidget(title)
        self.list = QListWidget(); layout.addWidget(self.list, 1)
        row = QHBoxLayout(); run_button = QPushButton("RUN ALL CHECKS"); run_button.setObjectName("primary")
        run_button.clicked.connect(self.refresh); close = QPushButton("CLOSE"); close.clicked.connect(self.accept)
        row.addWidget(run_button); row.addStretch(); row.addWidget(close); layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for check in run_health(self.registry):
            icon = "●" if check["ok"] else "○"
            self.list.addItem(f"{icon}  {check['name']}  /  {check['detail']}")
        cfg = load_config(); cfg.setdefault("onboarding", {})["diagnostics_run"] = True; save_config(cfg)


class PermissionsDialog(QDialog):
    def __init__(self, registry, parent=None):
        super().__init__(parent); self.registry = registry
        self.setWindowTitle("JARVIS V6 // APPLICATION PERMISSIONS"); self.resize(820, 600)
        layout = QVBoxLayout(self)
        info = QLabel("Sensitive mouse, keyboard, file and private-data actions are permanently locked to Always ask. Configure low-risk actions below.")
        info.setWordWrap(True); layout.addWidget(info)
        applications = sorted(registry.actions.get("open_app").values or []) if registry.actions.get("open_app") else []
        self.table = QTableWidget(len(registry.actions) + len(applications), 3)
        self.table.setHorizontalHeaderLabels(("Action", "Risk", "Permission"))
        cfg = load_config(); permission_cfg = cfg.get("permissions", {})
        overrides = permission_cfg.get("actions", {})
        app_overrides = permission_cfg.get("applications", {})
        self.combos = {}; self.app_combos = {}
        for row, (name, action) in enumerate(sorted(registry.actions.items())):
            self.table.setItem(row, 0, QTableWidgetItem(action.label))
            self.table.setItem(row, 1, QTableWidgetItem("Sensitive" if action.sensitive else "Low risk"))
            combo = QComboBox()
            if action.sensitive:
                combo.addItem("Always ask", "ask"); combo.setEnabled(False)
            else:
                combo.addItem("Use global policy", ""); combo.addItem("Allow automatically", "allow"); combo.addItem("Always ask", "ask")
                combo.setCurrentIndex(max(0, combo.findData(overrides.get(name, ""))))
            self.table.setCellWidget(row, 2, combo); self.combos[name] = combo
        first_app_row = len(registry.actions)
        for offset, application in enumerate(applications):
            row = first_app_row + offset
            self.table.setItem(row, 0, QTableWidgetItem(f"Open application: {application}"))
            self.table.setItem(row, 1, QTableWidgetItem("Application"))
            combo = QComboBox(); combo.addItem("Use global policy", "")
            combo.addItem("Allow automatically", "allow"); combo.addItem("Always ask", "ask")
            combo.setCurrentIndex(max(0, combo.findData(app_overrides.get(application, ""))))
            self.table.setCellWidget(row, 2, combo); self.app_combos[application] = combo
        self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table, 1)
        save_button = QPushButton("SAVE PERMISSIONS"); save_button.setObjectName("primary"); save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

    def _save(self):
        cfg = load_config(); cfg.setdefault("permissions", {})["actions"] = {
            name: combo.currentData() for name, combo in self.combos.items() if combo.currentData()
        }
        cfg["permissions"]["applications"] = {
            name: combo.currentData() for name, combo in self.app_combos.items() if combo.currentData()
        }
        save_config(cfg); self.accept()


class TodayDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.remaining = 0
        self.setWindowTitle("JARVIS V6 // TODAY + FOCUS"); self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.clock = QLabel("00:00"); self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet("font-size:42px;font-weight:600;letter-spacing:4px")
        layout.addWidget(self.clock)
        focus_row = QHBoxLayout(); start = QPushButton("START FOCUS"); start.setObjectName("primary")
        start.clicked.connect(self.start_focus); pause = QPushButton("PAUSE"); pause.clicked.connect(self.pause_focus)
        reset = QPushButton("RESET"); reset.clicked.connect(self.reset_focus)
        focus_row.addWidget(start); focus_row.addWidget(pause); focus_row.addWidget(reset); layout.addLayout(focus_row)
        layout.addWidget(QLabel("TODAY'S PRIORITIES"))
        self.items = QListWidget(); layout.addWidget(self.items, 1)
        row = QHBoxLayout(); self.entry = QLineEdit(); self.entry.setPlaceholderText("Add a concrete priority or next action")
        add = QPushButton("ADD"); add.clicked.connect(self.add_item)
        complete = QPushButton("COMPLETE SELECTED"); complete.clicked.connect(self.complete_item)
        row.addWidget(self.entry, 1); row.addWidget(add); row.addWidget(complete); layout.addLayout(row)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.refresh(); self.reset_focus()

    def refresh(self):
        self.rows = records("Today"); self.items.clear(); self.items.addItems([row[1] for row in self.rows])

    def add_item(self):
        text = self.entry.text().strip()
        if text: save("Today", text, f"Created {datetime.now().isoformat(timespec='minutes')}"); self.entry.clear(); self.refresh()

    def complete_item(self):
        index = self.items.currentRow()
        if index < 0 or index >= len(self.rows): return
        record_id, title, _body = self.rows[index]
        save("Completed", title, f"Completed {datetime.now().isoformat(timespec='minutes')}")
        delete_record(record_id); self.refresh()

    def start_focus(self):
        if self.remaining <= 0: self.reset_focus()
        self.timer.start(1000)

    def pause_focus(self): self.timer.stop()

    def reset_focus(self):
        self.timer.stop(); self.remaining = int(load_config().get("planning", {}).get("focus_session_minutes", 50)) * 60; self._draw()

    def tick(self):
        self.remaining = max(0, self.remaining - 1); self._draw()
        if self.remaining == 0: self.timer.stop(); QMessageBox.information(self, "Focus complete", "Focus session complete. Record the next action.")

    def _draw(self): self.clock.setText(f"{self.remaining // 60:02d}:{self.remaining % 60:02d}")


class BackupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("JARVIS V6 // ENCRYPTED BACKUP"); self.resize(620, 330)
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit(); self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Backup password", self.password); form.addRow("Confirm password", self.confirm)
        info = QLabel("The export is protected with AES-256-GCM. Credentials are excluded. Keep the password safe; it cannot be recovered.")
        info.setWordWrap(True); layout.addWidget(info); layout.addStretch()
        create_button = QPushButton("CREATE ENCRYPTED BACKUP"); create_button.setObjectName("primary"); create_button.clicked.connect(self.create)
        layout.addWidget(create_button)

    def create(self):
        if self.password.text() != self.confirm.text(): QMessageBox.warning(self, "Passwords differ", "Enter the same password twice."); return
        default = Path.home() / "Documents" / "JARVIS Backups" / f"JARVIS-V6-{datetime.now():%Y%m%d-%H%M}.j6backup"
        selected, _ = QFileDialog.getSaveFileName(self, "Save encrypted backup", str(default), "JARVIS backup (*.j6backup)")
        if not selected: return
        try: path = backup.create(Path(selected), self.password.text())
        except ValueError as exc: QMessageBox.warning(self, "Backup not created", str(exc)); return
        QMessageBox.information(self, "Backup created", f"Encrypted backup saved to:\n{path}"); self.accept()


class PerformanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("JARVIS V6 // PERFORMANCE"); self.resize(680, 480)
        layout = QVBoxLayout(self); self.list = QListWidget(); layout.addWidget(self.list)
        row = QHBoxLayout()
        refresh = QPushButton("REFRESH LATENCY"); refresh.clicked.connect(self.refresh)
        benchmark = QPushButton("RUN RELIABILITY BENCHMARK"); benchmark.setObjectName("primary")
        benchmark.clicked.connect(self.benchmark)
        row.addWidget(refresh); row.addWidget(benchmark); layout.addLayout(row); self.refresh()

    def refresh(self):
        self.list.clear(); rows = metric_snapshot()
        if not rows: self.list.addItem("No timed operations recorded in this session yet.")
        for row in rows:
            self.list.addItem(f"{row['name']}  /  latest {row['latest_ms']} ms  /  average {row['average_ms']} ms  /  max {row['maximum_ms']} ms  /  {row['count']} run(s)")

    def benchmark(self):
        report = run_benchmarks(write_report=True)
        self.list.clear()
        self.list.addItem(
            f"RELIABILITY SCORE  /  {report['passed']} PASSED  /  {report['failed']} FAILED  /  {report['total_ms']} ms")
        for case in report["cases"]:
            icon = "●" if case["passed"] else "○"
            self.list.addItem(f"{icon}  {case['name']}  /  {case['duration_ms']} ms\n     {case['detail']}")
        self.list.addItem("Report saved locally: " + report["report_path"])


class ActivityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("JARVIS V6 // SENSITIVE ACTIVITY"); self.resize(760, 520)
        layout = QVBoxLayout(self); listing = QListWidget(); layout.addWidget(listing)
        rows = recent_actions(100)
        if not rows: listing.addItem("No sensitive desktop actions recorded.")
        for created, action, detail, status in rows: listing.addItem(f"{created}  /  {action}  /  {status}  /  {detail}")
