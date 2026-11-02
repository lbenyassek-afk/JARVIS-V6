from __future__ import annotations

import math
import queue
import threading
from datetime import datetime

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QConicalGradient, QDesktopServices, QFont, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient, QKeySequence, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QInputDialog,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from core.commands import handle_memory_command
from core.config import load_config, save_config
from core.conversation import delete_history, recent_messages
from core.intent import is_weather_query, quick_reply, requested_location
from core.local_core import respond as local_core_response
from core.llm import LLMClient, normalize_gemini_key, route_mode, validate_gemini_key
from core.session import VoiceSession
from core.workspace import save as save_record
from ui.workspace import WorkspaceDialog
from core.instructions import load as load_instructions, save as save_instructions
from core.memory import delete_all, delete_one, search, update as update_memory
from core.manager_prompt import load as load_manager_prompt, restore_default as restore_manager_prompt, save as save_manager_prompt
from core.plugins import CATALOG as PLUGIN_CATALOG, enabled as plugin_enabled, set_enabled as set_plugins_enabled
from core.secrets import get_secret, set_secret
from core.skills import Registry
from core.tasks import Step, TaskExecutor
from core.voice import BRITISH_VOICES, is_cached_audio, synthesize
from core.weather import prefetch as prefetch_weather, report as weather_report
from core.audit import recent as recent_desktop_actions
from core.screen_context import snapshot as screen_snapshot
from core.updates import check as check_for_updates
from core.speech import transcribe_fast_free, transcribe_offline
from core.planner import build as build_execution_plan
from core import recovery
from ui.productivity import (
    ActivityDialog, BackupDialog, CommandPalette, DiagnosticsDialog,
    PerformanceDialog, PermissionsDialog, TodayDialog,
)


CYAN = QColor("#F1F4F7")
BLUE = QColor("#9EA8B2")
AMBER = QColor("#C8CED5")
INK = "#050607"
PANEL = "rgba(12, 14, 16, 238)"


class HudBackdrop(QWidget):
    def __init__(self):
        super().__init__(); self.scan = 0
        profile = load_config().get("interface", {}).get("motion_profile", "adaptive")
        timer = QTimer(self); timer.timeout.connect(self._animate)
        timer.start(90 if profile == "reduced" else 32 if profile == "cinematic" else 48)

    def _animate(self):
        self.scan = (self.scan + 2) % max(1, self.height()); self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QRadialGradient(QPointF(self.width() * .68, self.height() * .43), self.width() * .72)
        background.setColorAt(0, QColor(24, 28, 32)); background.setColorAt(.46, QColor(10, 12, 14))
        background.setColorAt(1, QColor(3, 4, 5)); painter.fillRect(self.rect(), background)
        painter.setPen(QPen(QColor(220, 228, 235, 12), 1))
        spacing = 42
        for x in range(0, self.width(), spacing): painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), spacing): painter.drawLine(0, y, self.width(), y)
        painter.setPen(QPen(QColor(230, 236, 242, 19), 1))
        for x in range(20, self.width(), 84):
            for y in range(20, self.height(), 84): painter.drawPoint(x, y)
        scan_gradient = QLinearGradient(0, self.scan - 35, 0, self.scan + 35)
        scan_gradient.setColorAt(0, QColor(238, 243, 248, 0)); scan_gradient.setColorAt(.5, QColor(238, 243, 248, 10))
        scan_gradient.setColorAt(1, QColor(238, 243, 248, 0)); painter.fillRect(0, self.scan - 35, self.width(), 70, scan_gradient)
        painter.setPen(QPen(QColor(205, 213, 221, 60), 2))
        length, pad = 55, 12
        for x, y, sx, sy in ((pad, pad, 1, 1), (self.width()-pad, pad, -1, 1),
                             (pad, self.height()-pad, 1, -1), (self.width()-pad, self.height()-pad, -1, -1)):
            painter.drawLine(x, y, x + sx * length, y); painter.drawLine(x, y, x, y + sy * length)
        super().paintEvent(event)


class BootOverlay(QFrame):
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bootOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self); layout.setContentsMargins(80, 80, 80, 80)
        layout.addStretch()
        mark = QLabel("J  /  04"); mark.setObjectName("bootMark"); mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage = QLabel("INITIALIZING"); self.stage.setObjectName("bootStage"); self.stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel("LOCAL SYSTEM"); self.detail.setObjectName("bootDetail"); self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar(); self.progress.setRange(0, 4); self.progress.setTextVisible(False); self.progress.setFixedWidth(280)
        layout.addWidget(mark); layout.addSpacing(28); layout.addWidget(self.stage); layout.addWidget(self.detail)
        layout.addSpacing(22); layout.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignCenter); layout.addStretch()
        self.steps = (("CORE", "GEMINI NEURAL ENGINE"), ("MEMORY", "LOCAL CONTEXT"),
                      ("VOICE", "ADAPTIVE ARRAY"), ("READY", "WELCOME BACK"))
        self.index = 0; self.timer = QTimer(self); self.timer.timeout.connect(self._advance)

    def start(self):
        self.show(); self.raise_(); self.index = 0; self.progress.setValue(0)
        QTimer.singleShot(120, self._advance)

    def _advance(self):
        if self.index >= len(self.steps):
            self.timer.stop(); self.hide(); self.finished.emit(); return
        stage, detail = self.steps[self.index]
        self.stage.setText(stage); self.detail.setText(detail)
        self.index += 1; self.progress.setValue(self.index)
        self.timer.start(230 if self.index < len(self.steps) else 320)


class AudioWaveform(QWidget):
    def __init__(self):
        super().__init__(); self.values = [0.04] * 36; self.setFixedHeight(72)

    def set_level(self, value: float):
        self.values = self.values[1:] + [max(.02, min(1.0, float(value)))]; self.update()

    def paintEvent(self, _event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.height() / 2; width = self.width() / max(1, len(self.values))
        pen = QPen(QColor(225, 231, 237, 205), max(1.4, width * .28))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); painter.setPen(pen)
        for index, value in enumerate(self.values):
            height = 4 + value * (self.height() * .72)
            x = (index + .5) * width
            painter.drawLine(QPointF(x, center - height / 2), QPointF(x, center + height / 2))
        painter.setPen(QPen(QColor(255, 193, 100, 35), 1)); painter.drawLine(0, int(center), self.width(), int(center))


class Task(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function, self.args, self.kwargs = function, args, kwargs

    def run(self):
        try:
            self.done.emit(self.function(*self.args, **self.kwargs))
        except Exception as exc:
            self.failed.emit(str(exc))


def microphone_level(device_name: str = "") -> float:
    """Measure a short microphone sample away from the GUI thread."""
    import numpy as np
    import sounddevice as sd
    index = None
    if device_name:
        for candidate_index, device in enumerate(sd.query_devices()):
            if device.get("max_input_channels", 0) > 0 and device.get("name") == device_name:
                index = candidate_index; break
    device = sd.query_devices(index, "input")
    native_rate = int(float(device.get("default_samplerate", 16_000)))
    rate = 16_000
    try:
        sd.check_input_settings(device=index, channels=1, samplerate=rate)
    except Exception:
        rate = max(8_000, min(native_rate, 48_000))
    capture = sd.rec(int(rate * 1.25), samplerate=rate, channels=1,
                     dtype="int16", device=index, blocking=True)
    return float(np.sqrt(np.mean(capture.astype("float32") ** 2)))


def desktop_context_data() -> tuple[dict, list[tuple]]:
    """Read desktop metadata and its encrypted audit away from the GUI."""
    return screen_snapshot(), recent_desktop_actions(24)


class AlwaysListener(QThread):
    """Adaptive low-latency capture; Gemini understands the completed turn once."""
    floor_cache = {}
    captured = pyqtSignal(bytes, int)
    activity = pyqtSignal(str)
    level = pyqtSignal(float)
    fault = pyqtSignal(str)

    def __init__(self, device_name: str = "", end_silence_ms: int = 550, parent=None):
        super().__init__(parent)
        self.device_name = str(device_name or "")
        self.end_silence_blocks = max(9, min(24, round(int(end_silence_ms) / 50)))
        self._stop = threading.Event()
        self._manual = threading.Event()

    def stop(self):
        self._stop.set()

    def force_capture(self):
        self._manual.set()
        self.activity.emit("MANUAL CAPTURE // SPEAK NOW")

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            devices = sd.query_devices()
            device_index = None
            if self.device_name:
                for index, candidate in enumerate(devices):
                    if candidate.get("max_input_channels", 0) > 0 and candidate.get("name") == self.device_name:
                        device_index = index; break
            device = sd.query_devices(device_index, "input")
            native_rate = int(float(device.get("default_samplerate", 16_000)))
            sample_rate = 16_000
            try:
                sd.check_input_settings(device=device_index, channels=1, samplerate=sample_rate)
            except Exception:
                sample_rate = max(8_000, min(native_rate, 48_000))
                sd.check_input_settings(device=device_index, channels=1, samplerate=sample_rate)
            blocksize = max(400, int(sample_rate * .05))
            frames: queue.Queue = queue.Queue(maxsize=160)

            def callback(indata, _frame_count, _time_info, status):
                if status:
                    self.activity.emit("MICROPHONE SIGNAL WARNING")
                try:
                    frames.put_nowait(indata.copy())
                except queue.Full:
                    try: frames.get_nowait()
                    except queue.Empty: pass

            cache_key = self.device_name or "__default__"
            floor = float(self.floor_cache.get(cache_key, .0015))
            calibration = []
            calibration_target = 4 if cache_key in self.floor_cache else 6
            pre_roll, active = [], []
            voiced = quiet = speech_blocks = 0
            speaking = False
            peak = 0.0
            self.activity.emit("CALIBRATING MICROPHONE")
            with sd.InputStream(device=device_index, samplerate=sample_rate, channels=1, dtype="int16",
                                blocksize=blocksize, callback=callback):
                while not self._stop.is_set():
                    try:
                        block = frames.get(timeout=.25)
                    except queue.Empty:
                        continue
                    signal = block[:, 0].astype("float32") / 32768.0
                    rms = float(np.sqrt(np.mean(signal * signal))) if signal.size else 0.0
                    if len(calibration) < calibration_target:
                        calibration.append(rms)
                        floor = max(.0008, float(np.median(calibration)))
                        self.level.emit(min(1.0, rms / max(.004, floor * 5)))
                        if self._manual.is_set():
                            self._manual.clear(); self.floor_cache[cache_key] = floor
                            speaking = True; active = [block]; quiet = speech_blocks = 0; peak = rms
                            calibration = [floor] * calibration_target
                            self.activity.emit("CAPTURING // SPEAK NOW")
                            continue
                        if len(calibration) == calibration_target:
                            self.floor_cache[cache_key] = floor
                            self.activity.emit("LISTENING // SPEAK NATURALLY")
                        continue
                    if not speaking and rms < floor * 2.2:
                        floor = floor * .97 + rms * .03
                    threshold = max(.0016, floor * 1.85)
                    voice = rms >= threshold
                    self.level.emit(min(1.0, rms / max(.006, threshold * 3.5)))
                    pre_roll.append(block)
                    pre_roll = pre_roll[-8:]
                    if not speaking:
                        if self._manual.is_set():
                            self._manual.clear(); speaking = True; active = list(pre_roll)
                            quiet = speech_blocks = 0; peak = rms
                            self.activity.emit("CAPTURING // SPEAK NOW")
                            continue
                        voiced = voiced + 1 if voice else 0
                        if voiced >= 2:
                            speaking = True; active = list(pre_roll); quiet = speech_blocks = 0; peak = rms
                            self.activity.emit("VOICE ACTIVITY DETECTED")
                        continue
                    active.append(block)
                    peak = max(peak, rms)
                    if voice:
                        speech_blocks += 1; quiet = 0
                    else:
                        quiet += 1
                    reached_end = quiet >= self.end_silence_blocks and speech_blocks >= 2
                    reached_limit = len(active) >= 300
                    if not (reached_end or reached_limit):
                        continue
                    pcm = np.concatenate(active, axis=0).astype("int16").tobytes()
                    if peak < threshold or speech_blocks < 2:
                        active, pre_roll, voiced, quiet, speech_blocks, speaking = [], [], 0, 0, 0, False
                        self.activity.emit("BACKGROUND AUDIO IGNORED")
                        continue
                    self.activity.emit("VOICE CAPTURED // GEMINI RESPONDING")
                    self.captured.emit(pcm, sample_rate)
                    return
        except Exception as exc:
            self.fault.emit(
                f"Microphone unavailable: {exc}. Open Windows Settings → Privacy & security → "
                "Microphone and allow desktop apps, then select the microphone in JARVIS Settings.")


class Reactor(QWidget):
    def __init__(self):
        super().__init__()
        self.angle = 0.0
        self.energy = 0.25
        self.state = "ONLINE"
        self.visual_mode = "hybrid"
        self.setMinimumSize(190, 190)
        self.setMaximumSize(260, 260)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        profile = load_config().get("interface", {}).get("motion_profile", "adaptive")
        timer.start(80 if profile == "reduced" else 24 if profile == "cinematic" else 38)

    def set_state(self, state: str):
        self.state = state.upper()
        self.energy = 1.0 if self.state in ("THINKING", "LISTENING") else 0.35
        self.update()

    def set_visual_mode(self, mode: str):
        self.visual_mode = mode if mode in ("core", "face", "hybrid") else "hybrid"
        self.update()

    def _tick(self):
        self.angle = (self.angle + 0.8 + self.energy * 1.4) % 360
        self.energy += (0.28 - self.energy) * 0.025
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        size = min(self.width(), self.height())
        pulse = 1 + math.sin(self.angle * 0.08) * 0.025

        # Volumetric halo behind the geometry.
        halo = QRadialGradient(center, size * .42)
        halo.setColorAt(0, QColor(255, 170, 43, 105))
        halo.setColorAt(.35, QColor(151, 78, 14, 45))
        halo.setColorAt(1, QColor(20, 9, 0, 0))
        painter.setBrush(halo); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, size * .43 * pulse, size * .43 * pulse)

        # Actual 3D coordinates projected to the screen. Each orbit sits in a
        # different plane; segments are depth-sorted so the rear half passes
        # behind the reactor and the near half crosses in front.
        yaw = math.radians(self.angle * .72)
        pitch = math.radians(58 + math.sin(self.angle * .018) * 8)
        segments = []
        rings = ((.35, 0.0, CYAN, 2.4), (.29, 1.15, AMBER, 1.8),
                 (.235, 2.3, QColor("#FFD183"), 1.5))
        for ring_index, (radius, tilt, color, width) in enumerate(rings):
            count = 96
            points = []
            for i in range(count + 1):
                t = i / count * math.tau + yaw * (-1 if ring_index % 2 else 1)
                x, y, z = math.cos(t) * radius, math.sin(t) * radius, 0.0
                # Tilt each ring around a unique axis, then rotate the assembly.
                cy, sy = math.cos(tilt), math.sin(tilt)
                y, z = y * cy - z * sy, y * sy + z * cy
                x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
                y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
                depth = 1.65 - z
                scale = size / depth
                points.append((QPointF(center.x() + x * scale, center.y() + y * scale), z))
            for i in range(count):
                if (i + ring_index * 9) % 17 in (0, 1, 2):
                    continue
                a, b = points[i], points[i + 1]
                segments.append(((a[1] + b[1]) / 2, a[0], b[0], color, width))
        segments.sort(key=lambda item: item[0])
        for depth, a, b, color, width in segments:
            alpha = int(max(55, min(245, 145 + depth * 260)))
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha),
                                max(.7, width + depth * 1.8), Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.drawLine(a, b)

        # Mechanical outer chassis, shaded around the circumference.
        chassis = QConicalGradient(center, -self.angle * 1.4)
        chassis.setColorAt(0, QColor("#241508")); chassis.setColorAt(.18, QColor("#FFF0C9"))
        chassis.setColorAt(.36, QColor("#100B07")); chassis.setColorAt(.62, QColor("#E89122"))
        chassis.setColorAt(.82, QColor("#63340C")); chassis.setColorAt(1, QColor("#241508"))
        painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(chassis, size * .022))
        painter.drawEllipse(center, size * .265 * pulse, size * .265 * pulse)

        # Reactor sphere: offset highlight + dark rim creates volume instead of
        # a flat disc. The small reflected flare moves with the orbit camera.
        core_radius = size * .112 * pulse
        sphere = QRadialGradient(center - QPointF(core_radius * .34, core_radius * .38), core_radius * 1.5)
        sphere.setColorAt(0, QColor("#FFFFFF")); sphere.setColorAt(.14, QColor("#FFF1C4"))
        sphere.setColorAt(.42, QColor("#FFC157")); sphere.setColorAt(.72, QColor("#D8790D"))
        sphere.setColorAt(1, QColor("#2B1203"))
        painter.setBrush(sphere); painter.setPen(QPen(QColor("#FFE6A8"), 2.4))
        painter.drawEllipse(center, core_radius, core_radius)
        painter.setBrush(QColor(255, 255, 255, 125)); painter.setPen(Qt.PenStyle.NoPen)
        flare = QPointF(center.x() - core_radius * .36 + math.cos(yaw) * 3,
                        center.y() - core_radius * .42)
        painter.drawEllipse(flare, core_radius * .15, core_radius * .08)

        # Floating energy particles reinforce parallax and depth.
        for i in range(18):
            phase = yaw * (1.2 + i % 3 * .2) + i * 2.31
            radius = size * (.15 + (i % 6) * .041)
            px = center.x() + math.cos(phase) * radius
            py = center.y() + math.sin(phase) * radius * (.42 + (i % 2) * .16)
            particle = 1.2 + (math.sin(phase * 1.7) + 1) * 1.1
            painter.setBrush(QColor(255, 178, 64, 80 + (i % 5) * 28))
            painter.drawEllipse(QPointF(px, py), particle, particle)

        # Cinematic targeting reticle: independent rings and radial data ticks.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius_factor, speed, alpha in ((.34, 1.0, 105), (.39, -1.35, 62), (.44, .55, 34)):
            radius = size * radius_factor
            rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            painter.setPen(QPen(QColor(255, 177, 59, alpha), max(.8, size * .003)))
            start = int((self.angle * speed) * 16)
            painter.drawArc(rect, start, 68 * 16); painter.drawArc(rect, start + 132 * 16, 42 * 16)
            painter.drawArc(rect, start + 226 * 16, 88 * 16)
        painter.setPen(QPen(QColor(255, 204, 122, 115), max(.7, size * .0025)))
        for index in range(72):
            angle = math.radians(index * 5 + self.angle * (-.22 if index % 3 else .15))
            outer = size * (.455 if index % 6 else .475)
            inner = outer - size * (.018 if index % 6 else .035)
            a = QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner)
            b = QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer)
            painter.drawLine(a, b)
        painter.setPen(QPen(QColor(255, 185, 75, 40), 1))
        painter.drawLine(QPointF(center.x() - size * .48, center.y()), QPointF(center.x() + size * .48, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - size * .48), QPointF(center.x(), center.y() + size * .48))

        if self.visual_mode in ("face", "hybrid"):
            face = QPainterPath()
            face.moveTo(center.x(), center.y() - size * .37)
            face.cubicTo(center.x() - size * .25, center.y() - size * .35,
                         center.x() - size * .31, center.y() - size * .05,
                         center.x() - size * .22, center.y() + size * .22)
            face.cubicTo(center.x() - size * .14, center.y() + size * .37,
                         center.x() - size * .06, center.y() + size * .42,
                         center.x(), center.y() + size * .44)
            face.cubicTo(center.x() + size * .06, center.y() + size * .42,
                         center.x() + size * .14, center.y() + size * .37,
                         center.x() + size * .22, center.y() + size * .22)
            face.cubicTo(center.x() + size * .31, center.y() - size * .05,
                         center.x() + size * .25, center.y() - size * .35,
                         center.x(), center.y() - size * .37)
            painter.setPen(QPen(QColor(255, 181, 70, 125), max(1.0, size * .004)))
            painter.drawPath(face)
            eye_y = center.y() - size * .075
            for side in (-1, 1):
                eye = QPainterPath()
                eye.moveTo(center.x() + side * size * .07, eye_y)
                eye.lineTo(center.x() + side * size * .15, eye_y - size * .025)
                eye.lineTo(center.x() + side * size * .22, eye_y + size * .005)
                painter.setPen(QPen(QColor(255, 236, 193, 220), max(1.2, size * .006)))
                painter.drawPath(eye)
                painter.setPen(QPen(QColor(255, 177, 69, 145), max(1.0, size * .003)))
                painter.drawLine(QPointF(center.x() + side * size * .255, center.y() - size * .13),
                                 QPointF(center.x() + side * size * .28, center.y() + size * .03))
            painter.setPen(QPen(QColor(255, 185, 77, 90), max(.8, size * .0025)))
            painter.drawLine(QPointF(center.x() - size * .07, center.y() + size * .22),
                             QPointF(center.x() + size * .07, center.y() + size * .22))

        painter.setPen(QColor("#FFF1D1"))
        painter.setFont(QFont("Segoe UI", max(9, int(size * .025)), QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, center.y() + size * .40, self.width(), 30),
                         Qt.AlignmentFlag.AlignHCenter, self.state)


class Metric(QWidget):
    def __init__(self, name: str, color=CYAN):
        super().__init__()
        self.name, self.value, self.color = name, 0, color
        self.setFixedHeight(54)

    def set_value(self, value: float):
        self.value = max(0, min(100, value)); self.update()

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("#9A8061")); p.setFont(QFont("Consolas", 8))
        p.drawText(0, 14, self.name.upper())
        p.setPen(QColor("#FFF0D2")); p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignRight, f"{self.value:04.1f}%")
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(48, 31, 15, 220))
        p.drawRoundedRect(QRectF(0, 28, self.width(), 7), 3, 3)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 28, self.width() * self.value / 100, 7), 3, 3)


class ApiKeyDialog(QDialog):
    connected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS // GEMINI SETUP")
        self.setModal(True); self.resize(590, 430); self.setMinimumWidth(540)
        self.thread = None; self.worker = None; self.pending_key = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 26, 28, 26); layout.setSpacing(14)
        title = QLabel("CONNECT GEMINI"); title.setObjectName("section"); layout.addWidget(title)
        intro = QLabel(
            "JARVIS uses one free Gemini API key for chat and voice. Create it in Google AI Studio, "
            "copy it, then paste it below. It will be tested before Windows Credential Manager stores it."
        )
        intro.setWordWrap(True); layout.addWidget(intro)
        open_studio = QPushButton("1  OPEN GOOGLE AI STUDIO")
        open_studio.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey")))
        layout.addWidget(open_studio)
        key_row = QHBoxLayout()
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste the Gemini API key here")
        self.key.setClearButtonEnabled(True); self.key.returnPressed.connect(self._test)
        paste = QPushButton("PASTE"); paste.clicked.connect(self._paste)
        key_row.addWidget(self.key, 1); key_row.addWidget(paste); layout.addLayout(key_row)
        show = QCheckBox("Show key while typing"); show.toggled.connect(
            lambda visible: self.key.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        layout.addWidget(show)
        self.status = QLabel("● A key is already stored securely" if get_secret("gemini_api_key") else "○ No Gemini key stored")
        self.status.setObjectName("keyStatus"); self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addStretch()
        row = QHBoxLayout()
        remove = QPushButton("REMOVE STORED KEY"); remove.setEnabled(bool(get_secret("gemini_api_key")))
        remove.clicked.connect(self._remove)
        self.test_button = QPushButton("2  TEST AND SAVE KEY"); self.test_button.setObjectName("primary")
        self.test_button.clicked.connect(self._test)
        row.addWidget(remove); row.addStretch(); row.addWidget(self.test_button); layout.addLayout(row)

    def _paste(self):
        value = QApplication.clipboard().text().strip()
        if value:
            self.key.setText(value); self.status.setText("○ Key pasted — test it to continue")
        else:
            self.status.setText("○ Clipboard has no text")

    def _test(self):
        candidate = normalize_gemini_key(self.key.text()) or get_secret("gemini_api_key")
        if not candidate:
            self.status.setText("● Paste a Gemini API key first"); self.key.setFocus(); return
        self.pending_key = candidate
        self.test_button.setEnabled(False); self.key.setEnabled(False)
        self.status.setText("● Testing network, key, model and generation…")
        self.thread = QThread(self); self.worker = Task(validate_gemini_key, candidate, True)
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.done.connect(self._connected); self.worker.failed.connect(self._failed)
        self.worker.done.connect(self.thread.quit); self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def _thread_finished(self):
        self.thread = None; self.worker = None

    def _connected(self, message):
        try:
            set_secret("gemini_api_key", self.pending_key)
            if not get_secret("gemini_api_key"):
                raise RuntimeError("Windows Credential Manager did not retain the key")
        except Exception as exc:
            self._failed("Gemini connected, but secure storage failed: " + str(exc)); return
        self.key.clear(); self.status.setText("● " + str(message) + " Key stored securely.")
        self.connected.emit(); QTimer.singleShot(500, self.accept)

    def _failed(self, message):
        self.status.setText("● " + str(message))
        self.test_button.setEnabled(True); self.key.setEnabled(True); self.key.setFocus()

    def _remove(self):
        if QMessageBox.question(self, "Remove Gemini key?", "JARVIS chat and voice will stop until another key is added.") == QMessageBox.StandardButton.Yes:
            set_secret("gemini_api_key", ""); self.status.setText("○ Gemini key removed"); self.key.clear()

    def reject(self):
        if self.thread is not None and self.thread.isRunning():
            self.status.setText("● Please wait for the connection test to finish")
            return
        super().reject()


class SettingsDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS // SYSTEM CONFIGURATION")
        self.resize(680, 720); self.setMinimumWidth(600)
        cfg = load_config()
        layout = QVBoxLayout(self); scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); form = QFormLayout(content); form.setSpacing(11)
        scroll.setWidget(content); layout.addWidget(scroll)
        self.name = QLineEdit(cfg["assistant"]["name"])
        self.user = QLineEdit(cfg["assistant"]["user_name"])
        self.provider = QLabel("Adaptive router — Gemini active")
        self.gemini_models = QLabel("Fast / research / reflection routing")
        self.key_status = QLabel("● Key saved securely" if get_secret("gemini_api_key") else "○ Gemini key required")
        self.key_status.setObjectName("keyStatus")
        self.manage_key = QPushButton("OPEN GEMINI KEY SETUP"); self.manage_key.clicked.connect(self._manage_key)
        self.speak = QCheckBox(); self.speak.setChecked(cfg["voice"]["speak_replies"])
        self.input_engine = QComboBox()
        self.input_engine.addItem("Fast online English — free, no API key", "fast_free")
        self.input_engine.addItem("Private offline English — basic accuracy", "offline")
        self.input_engine.addItem("Gemini audio — higher accuracy, uses quota", "gemini")
        self.input_engine.setCurrentIndex(max(0, self.input_engine.findData(cfg["voice"].get("input_engine", "fast_free"))))
        self.activation_mode = QComboBox()
        self.activation_mode.addItem("Natural conversation — no wake phrase", "natural")
        self.activation_mode.addItem("Wake phrase required after timeout", "wake")
        self.activation_mode.setCurrentIndex(max(0, self.activation_mode.findData(cfg["voice"].get("activation_mode", "natural"))))
        self.wake_phrase = QLineEdit(cfg["voice"].get("wake_phrase", "hey jarvis"))
        self.wake_phrase.setMaxLength(40)
        self.voice = QComboBox()
        for label, value in BRITISH_VOICES.items(): self.voice.addItem(label, value)
        current_voice = cfg["voice"].get("british_voice", "en-GB-ThomasNeural")
        index = self.voice.findData(current_voice); self.voice.setCurrentIndex(max(0, index))
        self.voice_preview = QPushButton("PREVIEW CINEMATIC VOICE")
        self.voice_preview.clicked.connect(self._preview_voice)
        self.always_listening = QCheckBox(); self.always_listening.setChecked(cfg["voice"].get("always_listening", True))
        self.english_only = QCheckBox(); self.english_only.setChecked(cfg["voice"].get("english_only", True))
        self.english_only.setEnabled(self.input_engine.currentData() == "gemini")
        self.input_engine.currentIndexChanged.connect(
            lambda: self.english_only.setEnabled(self.input_engine.currentData() == "gemini"))
        self.end_silence = QSpinBox(); self.end_silence.setRange(450, 1200); self.end_silence.setSingleStep(50)
        self.end_silence.setSuffix(" ms"); self.end_silence.setValue(int(cfg["voice"].get("end_silence_ms", 550)))
        self.speech_rate = QSpinBox(); self.speech_rate.setRange(-20, 20); self.speech_rate.setSuffix(" %")
        self.speech_rate.setValue(int(cfg["voice"].get("speech_rate", 0)))
        self.speech_pitch = QSpinBox(); self.speech_pitch.setRange(-10, 10); self.speech_pitch.setSuffix(" Hz")
        self.speech_pitch.setValue(int(cfg["voice"].get("speech_pitch", 0)))
        self.speech_volume = QSpinBox(); self.speech_volume.setRange(40, 100); self.speech_volume.setSuffix(" %")
        self.speech_volume.setValue(int(cfg["voice"].get("speech_volume", 90)))
        self.microphone = QComboBox(); self.microphone.addItem("System default microphone", "")
        try:
            import sounddevice as sd
            for device in sd.query_devices():
                if device.get("max_input_channels", 0) > 0:
                    name = str(device.get("name", "Microphone"))
                    if self.microphone.findData(name) < 0:
                        self.microphone.addItem(name, name)
        except Exception:
            pass
        selected_mic = self.microphone.findData(cfg["voice"].get("input_device", ""))
        self.microphone.setCurrentIndex(max(0, selected_mic))
        self.mic_test = QPushButton("TEST SELECTED MICROPHONE"); self.mic_test.clicked.connect(self._test_microphone)
        self.serious = QCheckBox(); self.serious.setChecked(cfg["assistant"].get("serious_mode", False))
        self.desktop = QCheckBox(); self.desktop.setChecked(cfg["desktop"].get("enabled", False))
        self.screen_observation = QCheckBox(); self.screen_observation.setChecked(cfg["desktop"].get("screen_observation", True))
        self.automatic_actions = QCheckBox()
        self.automatic_actions.setChecked(cfg.get("permissions", {}).get("low_risk", "automatic") == "automatic")
        self.adaptive_layout = QCheckBox(); self.adaptive_layout.setChecked(cfg["interface"].get("adaptive_layout", True))
        self.motion_profile = QComboBox()
        self.motion_profile.addItem("Adaptive performance", "adaptive")
        self.motion_profile.addItem("Cinematic", "cinematic")
        self.motion_profile.addItem("Reduced motion", "reduced")
        self.motion_profile.setCurrentIndex(max(0, self.motion_profile.findData(cfg["interface"].get("motion_profile", "adaptive"))))
        self.update_channel = QComboBox(); self.update_channel.addItem("Stable", "stable")
        self.update_channel.addItem("Experimental", "experimental")
        self.update_channel.setCurrentIndex(max(0, self.update_channel.findData(cfg.get("updates", {}).get("channel", "stable"))))
        self.quick_replies = QCheckBox(); self.quick_replies.setChecked(cfg["assistant"].get("quick_local_replies", True))
        self.daily_focus = QLineEdit(cfg["assistant"].get("daily_focus", ""))
        self.daily_focus.setPlaceholderText("Your most important current outcome")
        self.weather_location = QLineEdit(cfg.get("weather", {}).get("location", ""))
        self.weather_location.setPlaceholderText("City, or leave blank for automatic location")
        self.auto_location = QCheckBox(); self.auto_location.setChecked(cfg.get("weather", {}).get("automatic_location", True))
        self.weather_units = QComboBox(); self.weather_units.addItem("Celsius / km/h", "metric")
        self.weather_units.addItem("Fahrenheit / mph", "imperial")
        self.weather_units.setCurrentIndex(max(0, self.weather_units.findData(cfg.get("weather", {}).get("units", "metric"))))
        self.focus_minutes = QSpinBox(); self.focus_minutes.setRange(15, 120); self.focus_minutes.setSuffix(" min")
        self.focus_minutes.setValue(int(cfg.get("planning", {}).get("focus_session_minutes", 50)))
        self.daily_priorities = QSpinBox(); self.daily_priorities.setRange(1, 7)
        self.daily_priorities.setValue(int(cfg.get("planning", {}).get("max_daily_priorities", 3)))
        self.daily_review = QCheckBox(); self.daily_review.setChecked(cfg.get("planning", {}).get("daily_review", True))
        self.memory_enabled = QCheckBox(); self.memory_enabled.setChecked(cfg["memory"].get("enabled", True))
        self.chat_history = QCheckBox(); self.chat_history.setChecked(cfg["memory"].get("chat_history_enabled", True))
        self.chat_context = QSpinBox(); self.chat_context.setRange(8, 48); self.chat_context.setSingleStep(2)
        self.chat_context.setValue(int(cfg["memory"].get("chat_context_messages", 24)))
        self.memory_budget = QSpinBox(); self.memory_budget.setRange(400, 6000); self.memory_budget.setSingleStep(200)
        self.memory_budget.setValue(int(cfg["memory"].get("prompt_budget", 1800)))
        self.instructions = QPlainTextEdit(load_instructions()); self.instructions.setPlaceholderText(
            "Add your own working rules. Never put API keys or passwords here.")
        self.instructions.setMinimumHeight(110)
        for label, widget in (
            ("Assistant name", self.name), ("Your preferred name", self.user),
            ("AI provider", self.provider), ("Gemini modes", self.gemini_models),
            ("Gemini connection", self.key_status), ("API key setup", self.manage_key),
            ("Speak replies", self.speak),
            ("Speech recognition", self.input_engine),
            ("Listening behaviour", self.activation_mode),
            ("Wake phrase", self.wake_phrase),
            ("British voice", self.voice),
            ("Voice preview", self.voice_preview),
            ("Always-listening microphone", self.always_listening),
            ("Microphone", self.microphone), ("Microphone check", self.mic_test),
            ("Wait after speech", self.end_silence),
            ("English commands only", self.english_only),
            ("Voice speed", self.speech_rate), ("Voice pitch", self.speech_pitch),
            ("Voice volume", self.speech_volume),
            ("Serious mode", self.serious),
            ("Desktop Control", self.desktop),
            ("Transient screen context", self.screen_observation),
            ("Automatic low-risk actions", self.automatic_actions),
            ("Adaptive interface layout", self.adaptive_layout),
            ("Animation profile", self.motion_profile),
            ("Update channel", self.update_channel),
            ("Instant local replies", self.quick_replies),
            ("Daily focus", self.daily_focus),
            ("Weather city", self.weather_location),
            ("Automatic location", self.auto_location),
            ("Weather units", self.weather_units),
            ("Focus session", self.focus_minutes),
            ("Maximum daily priorities", self.daily_priorities),
            ("Daily review", self.daily_review),
            ("Use long-term memory", self.memory_enabled),
            ("Remember chat history", self.chat_history),
            ("Chat context messages", self.chat_context),
            ("Memory prompt budget", self.memory_budget),
            ("Custom instructions", self.instructions),
        ): form.addRow(label, widget)
        self.save_button = QPushButton("SAVE SETTINGS"); self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save); form.addRow(self.save_button)

    def _manage_key(self):
        dialog = ApiKeyDialog(self)
        dialog.connected.connect(lambda: self.key_status.setText("● Gemini connected securely"))
        dialog.exec()
        self.key_status.setText("● Key saved securely" if get_secret("gemini_api_key") else "○ Gemini key required")

    def _save(self):
        cfg = load_config()
        cfg["assistant"]["name"] = self.name.text().strip() or "JARVIS"
        cfg["assistant"]["user_name"] = self.user.text().strip()
        cfg["llm"]["provider"] = "gemini"
        cfg["voice"]["speak_replies"] = self.speak.isChecked()
        cfg["voice"]["input_engine"] = self.input_engine.currentData()
        cfg["voice"]["activation_mode"] = self.activation_mode.currentData()
        wake = " ".join(self.wake_phrase.text().casefold().split()) or "hey jarvis"
        cfg["voice"]["wake_phrase"] = wake
        cfg["voice"]["wake_phrases"] = list(dict.fromkeys([wake, "jarvis"]))
        cfg["voice"]["british_voice"] = self.voice.currentData()
        cfg["voice"]["always_listening"] = self.always_listening.isChecked()
        cfg["voice"]["input_device"] = self.microphone.currentData() or ""
        cfg["voice"]["english_only"] = self.english_only.isChecked()
        cfg["voice"]["end_silence_ms"] = self.end_silence.value()
        cfg["voice"]["speech_rate"] = self.speech_rate.value()
        cfg["voice"]["speech_pitch"] = self.speech_pitch.value()
        cfg["voice"]["speech_volume"] = self.speech_volume.value()
        cfg["assistant"]["serious_mode"] = self.serious.isChecked()
        cfg["assistant"]["quick_local_replies"] = self.quick_replies.isChecked()
        cfg["assistant"]["daily_focus"] = self.daily_focus.text().strip()[:300]
        cfg["desktop"]["enabled"] = self.desktop.isChecked()
        cfg["desktop"]["screen_observation"] = self.screen_observation.isChecked()
        cfg["desktop"]["automatic_approved_actions"] = self.automatic_actions.isChecked()
        cfg["permissions"]["low_risk"] = "automatic" if self.automatic_actions.isChecked() else "ask"
        cfg["interface"]["adaptive_layout"] = self.adaptive_layout.isChecked()
        cfg["interface"]["motion_profile"] = self.motion_profile.currentData()
        cfg["interface"]["reduced_motion"] = self.motion_profile.currentData() == "reduced"
        cfg["updates"]["channel"] = self.update_channel.currentData()
        cfg["weather"]["location"] = self.weather_location.text().strip()[:100]
        cfg["weather"]["automatic_location"] = self.auto_location.isChecked()
        cfg["weather"]["units"] = self.weather_units.currentData()
        cfg["planning"]["focus_session_minutes"] = self.focus_minutes.value()
        cfg["planning"]["max_daily_priorities"] = self.daily_priorities.value()
        cfg["planning"]["daily_review"] = self.daily_review.isChecked()
        cfg["memory"]["enabled"] = self.memory_enabled.isChecked()
        cfg["memory"]["chat_history_enabled"] = self.chat_history.isChecked()
        cfg["memory"]["chat_context_messages"] = self.chat_context.value()
        cfg["memory"]["prompt_budget"] = self.memory_budget.value()
        try:
            save_instructions(self.instructions.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Instructions not saved", str(exc)); return
        save_config(cfg)
        QMessageBox.information(self, "Settings saved", "Your JARVIS settings are active.")
        self.saved.emit(); self.accept()

    def _test_microphone(self):
        self.mic_test.setEnabled(False); self.mic_test.setText("LISTENING — SPEAK NOW…")
        self.mic_test_thread = QThread(self)
        self.mic_test_worker = Task(microphone_level, self.microphone.currentData() or "")
        self.mic_test_worker.moveToThread(self.mic_test_thread)
        self.mic_test_thread.started.connect(self.mic_test_worker.run)
        self.mic_test_worker.done.connect(self._microphone_tested)
        self.mic_test_worker.failed.connect(self._microphone_test_failed)
        self.mic_test_worker.done.connect(self.mic_test_thread.quit)
        self.mic_test_worker.failed.connect(self.mic_test_thread.quit)
        self.mic_test_thread.start()

    def _preview_voice(self):
        self.voice_preview.setEnabled(False); self.voice_preview.setText("GENERATING PREVIEW…")
        self.preview_thread = QThread(self)
        self.preview_worker = Task(
            synthesize, "Good evening, Reda. All systems are online. How may I assist you?",
            self.voice.currentData(), self.speech_rate.value(), self.speech_pitch.value())
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.done.connect(self._preview_ready)
        self.preview_worker.failed.connect(self._preview_failed)
        self.preview_worker.done.connect(self.preview_thread.quit)
        self.preview_worker.failed.connect(self.preview_thread.quit)
        self.preview_thread.start()

    def _preview_ready(self, path):
        if not hasattr(self, "preview_player"):
            self.preview_audio = QAudioOutput(self); self.preview_player = QMediaPlayer(self)
            self.preview_player.setAudioOutput(self.preview_audio)
        self.preview_audio.setVolume(float(self.speech_volume.value()) / 100.0)
        self.preview_player.setSource(QUrl.fromLocalFile(str(path))); self.preview_player.play()
        self.voice_preview.setEnabled(True); self.voice_preview.setText("PREVIEW CINEMATIC VOICE")

    def _preview_failed(self, error):
        self.voice_preview.setEnabled(True); self.voice_preview.setText("PREVIEW CINEMATIC VOICE")
        QMessageBox.warning(self, "Voice preview unavailable", str(error))

    def _microphone_tested(self, rms):
        self.mic_test.setEnabled(True); self.mic_test.setText("TEST SELECTED MICROPHONE")
        if float(rms) >= 120:
            QMessageBox.information(self, "Microphone works", "Voice detected. This microphone is ready.")
        else:
            QMessageBox.warning(self, "No voice detected",
                                "The microphone was very quiet. Select another microphone or check Windows microphone access.")

    def _microphone_test_failed(self, error):
        self.mic_test.setEnabled(True); self.mic_test.setText("TEST SELECTED MICROPHONE")
        QMessageBox.warning(self, "Microphone test failed", str(error))


class MemoryDialog(QDialog):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("JARVIS // LONG-TERM MEMORY"); self.resize(700, 500)
        layout = QVBoxLayout(self); self.list = QListWidget(); layout.addWidget(self.list, 1)
        row = QHBoxLayout(); edit = QPushButton("EDIT"); edit.clicked.connect(self._edit)
        pin = QPushButton("PIN / UNPIN"); pin.clicked.connect(self._toggle_pin)
        delete = QPushButton("DELETE SELECTED"); delete.clicked.connect(self._delete)
        erase = QPushButton("DELETE ALL"); erase.clicked.connect(self._erase); row.addWidget(delete); row.addWidget(erase)
        row.insertWidget(0, pin); row.insertWidget(0, edit)
        history = QPushButton("DELETE CHAT HISTORY"); history.clicked.connect(self._erase_history); row.addWidget(history)
        layout.addLayout(row); self._refresh()

    def _refresh(self):
        self.list.clear()
        for item in search("", 500):
            marker = "★" if item.get("pinned") else "·"
            self.list.addItem(
                f"{marker} {item['category']} / {item['key']}  [importance {item.get('importance', 3)}] — {item['value']}")
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, (item["category"], item["key"]))

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _edit(self):
        selected = self._selected()
        if not selected: return
        category, key = selected
        current = next((row for row in search("", 500)
                        if row["category"] == category and row["key"] == key), None)
        if not current: return
        value, accepted = QInputDialog.getMultiLineText(
            self, "Edit organized memory", f"{category} / {key}", current["value"])
        if accepted and value.strip():
            try: update_memory(category, key, value=value)
            except ValueError as exc: QMessageBox.warning(self, "Memory not saved", str(exc)); return
            self._refresh(); self.changed.emit()

    def _toggle_pin(self):
        selected = self._selected()
        if not selected: return
        category, key = selected
        current = next((row for row in search("", 500)
                        if row["category"] == category and row["key"] == key), None)
        if current and update_memory(category, key, pinned=not current.get("pinned", False)):
            self._refresh(); self.changed.emit()

    def _delete(self):
        item = self.list.currentItem()
        if item and delete_one(*item.data(Qt.ItemDataRole.UserRole)):
            self._refresh(); self.changed.emit()

    def _erase(self):
        if QMessageBox.question(self, "Delete every memory?", "This cannot be undone.") == QMessageBox.StandardButton.Yes:
            delete_all(); self._refresh(); self.changed.emit()

    def _erase_history(self):
        if QMessageBox.question(self, "Delete chat history?",
                                "This removes the saved conversation context from V4.") == QMessageBox.StandardButton.Yes:
            delete_history()
            QMessageBox.information(self, "Chat history deleted", "Saved conversation context was removed.")


class PluginManagerDialog(QDialog):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS // PLUGIN MANAGER")
        self.resize(720, 610)
        cfg = load_config(); states = cfg.get("plugins", {}).get("enabled", {})
        layout = QVBoxLayout(self)
        title = QLabel("PLUGIN MANAGER"); title.setObjectName("section"); layout.addWidget(title)
        info = QLabel("Plugins expose separate capabilities and permissions. Desktop plans remain visible before execution, and EMERGENCY STOP is always available.")
        info.setWordWrap(True); layout.addWidget(info)
        self.boxes = {}
        for plugin in PLUGIN_CATALOG:
            card = QFrame(); card.setObjectName("dataCard"); card_layout = QVBoxLayout(card)
            checkbox = QCheckBox(plugin.name)
            checkbox.setChecked(bool(states.get(plugin.plugin_id, False)) and plugin.installed)
            checkbox.setEnabled(plugin.installed)
            detail = QLabel(plugin.description + "\nPERMISSIONS // " + plugin.permissions)
            detail.setWordWrap(True); detail.setObjectName("hint")
            card_layout.addWidget(checkbox); card_layout.addWidget(detail); layout.addWidget(card)
            self.boxes[plugin.plugin_id] = checkbox
        layout.addStretch()
        save = QPushButton("SAVE PLUGIN ACCESS"); save.setObjectName("primary")
        save.clicked.connect(self._save); layout.addWidget(save)

    def _save(self):
        set_plugins_enabled({plugin_id: box.isChecked() for plugin_id, box in self.boxes.items()})
        self.changed.emit(); self.accept()


class ManagerPromptDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS // MANAGER PROMPT")
        self.resize(760, 620)
        cfg = load_config(); layout = QVBoxLayout(self)
        title = QLabel("MANAGER PROMPT"); title.setObjectName("section"); layout.addWidget(title)
        info = QLabel("This prompt coordinates priorities, projects and enabled plugins. It is separate from chat memory and cannot contain credentials.")
        info.setWordWrap(True); layout.addWidget(info)
        self.enabled = QCheckBox("Manager mode active")
        self.enabled.setChecked(cfg["assistant"].get("manager_enabled", True)); layout.addWidget(self.enabled)
        self.editor = QPlainTextEdit(load_manager_prompt()); layout.addWidget(self.editor, 1)
        row = QHBoxLayout(); restore = QPushButton("RESTORE DEFAULT"); restore.clicked.connect(self._restore)
        save = QPushButton("SAVE MANAGER PROMPT"); save.setObjectName("primary"); save.clicked.connect(self._save)
        row.addWidget(restore); row.addStretch(); row.addWidget(save); layout.addLayout(row)

    def _restore(self):
        self.editor.setPlainText(restore_manager_prompt())

    def _save(self):
        try:
            save_manager_prompt(self.editor.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Manager Prompt not saved", str(exc)); return
        cfg = load_config(); cfg["assistant"]["manager_enabled"] = self.enabled.isChecked(); save_config(cfg)
        self.accept()


class TaskStudio(QDialog):
    run_plan = pyqtSignal(list)

    def __init__(self, registry: Registry, parent=None):
        super().__init__(parent); self.registry = registry
        self.setWindowTitle("JARVIS // SERIOUS MODE TASK STUDIO"); self.resize(720, 540)
        layout = QVBoxLayout(self)
        info = QLabel("Build an approved desktop plan. JARVIS never runs shell commands or unlisted actions.")
        info.setWordWrap(True); layout.addWidget(info)
        form = QFormLayout(); self.action = QComboBox();
        for name, action in registry.actions.items(): self.action.addItem(action.label, name)
        self.value = QComboBox(); self.value.setEditable(True); self.action.currentIndexChanged.connect(self._values)
        form.addRow("Action", self.action); form.addRow("Value", self.value); layout.addLayout(form); self._values()
        add = QPushButton("ADD STEP"); add.clicked.connect(self._add); layout.addWidget(add)
        self.steps = QListWidget(); layout.addWidget(self.steps, 1)
        row = QHBoxLayout(); remove = QPushButton("REMOVE STEP"); remove.clicked.connect(self._remove)
        clear = QPushButton("CLEAR PLAN"); clear.clicked.connect(self.steps.clear)
        run = QPushButton("REVIEW & RUN PLAN"); run.clicked.connect(self._run)
        row.addWidget(remove); row.addWidget(clear); row.addStretch(); row.addWidget(run); layout.addLayout(row)

    def _values(self):
        action = self.registry.actions.get(self.action.currentData())
        self.value.clear()
        if action and action.values:
            self.value.addItems(action.values); self.value.setEditable(False)
        else:
            self.value.setEditable(True); self.value.setEditText("")

    def _add(self):
        step = Step(str(self.action.currentData()), self.value.currentText())
        action = self.registry.actions[step.action]
        item = self.steps.addItem(f"{self.steps.count() + 1}. {action.label}: {step.value[:100]}")
        self.steps.item(self.steps.count() - 1).setData(Qt.ItemDataRole.UserRole, step)

    def _remove(self):
        row = self.steps.currentRow()
        if row >= 0: self.steps.takeItem(row)

    def _run(self):
        plan = [self.steps.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.steps.count())]
        if not plan:
            QMessageBox.information(self, "Empty plan", "Add at least one step."); return
        self.run_plan.emit(plan); self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = LLMClient(); self.threads = []
        self.recovery_state = recovery.begin()
        voice_cfg = load_config()["voice"]
        self.voice_session = VoiceSession(
            voice_cfg["session_timeout"], voice_cfg["wake_phrase"], voice_cfg.get("wake_phrases"))
        self._pending_wake_required = False
        self.always_listener = None
        self.retired_listeners = []
        self._desktop_refresh_pending = False
        self._recovery_pending = False
        self._last_recovery_state = None
        self.chat_mode = "auto"
        self._active_mode = "chat"
        self.audio_output = None
        self.media_player = None
        self._voice_file = ""
        self.registry = Registry(); self.registry.discover(__import__('pathlib').Path(__file__).resolve().parent.parent / "skills")
        self.task_executor = TaskExecutor(self.registry)
        self.global_hotkey = None
        self.setWindowTitle("JARVIS V6 // Created by Reda Benyassek")
        self.resize(1240, 800); self.setMinimumSize(920, 640)
        self.setStyleSheet(self._style())
        self._build(); self._start_timers(); self._install_emergency_stop(); self._install_productivity_shortcuts()
        self.boot = BootOverlay(self.centralWidget()); self.boot.setGeometry(self.centralWidget().rect())
        self.boot.finished.connect(self._first_run); self.boot.start()

    def _build(self):
        root = HudBackdrop(); root.setObjectName("hudRoot"); self.setCentralWidget(root); outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 22); outer.setSpacing(14)
        header = QHBoxLayout()
        brand = QLabel("JARVIS"); brand.setObjectName("brand")
        creator = QLabel("PERSONAL INTELLIGENCE  /  REDA BENYASSEK"); creator.setObjectName("creator")
        self.clock = QLabel(); self.clock.setObjectName("clock")
        self.status = QLabel("● ONLINE"); self.status.setObjectName("online")
        engine = QLabel("ADAPTIVE CORE  /  V6.0.0"); engine.setObjectName("engine")
        self.context_selector = QComboBox()
        for label, value in (("PERSONAL", "personal"), ("SCHOOL", "school"), ("BUSINESS", "business")):
            self.context_selector.addItem(label, value)
        active_context = load_config()["assistant"].get("active_mode", "personal")
        self.context_selector.setCurrentIndex(max(0, self.context_selector.findData(active_context)))
        self.context_selector.currentIndexChanged.connect(self._change_context)
        self.window_selector = QComboBox()
        for label, value in (("NORMAL", "normal"), ("FULL SCREEN", "fullscreen"), ("FLOATING", "floating")):
            self.window_selector.addItem(label, value)
        self.window_selector.currentIndexChanged.connect(
            lambda: self.apply_window_mode(str(self.window_selector.currentData())))
        title = QVBoxLayout(); title.setSpacing(1); title.addWidget(brand); title.addWidget(creator)
        header.addLayout(title); header.addStretch(); header.addWidget(self.context_selector)
        header.addWidget(self.window_selector); header.addWidget(engine); header.addWidget(self.status)
        header.addWidget(self.clock)
        outer.addLayout(header)

        body = QHBoxLayout(); body.setSpacing(14); outer.addLayout(body, 1)
        rail = self._panel(); self.rail = rail; rail.setObjectName("rail"); rail.setFixedWidth(158)
        rail_layout = QVBoxLayout(rail); rail_layout.setContentsMargins(10, 14, 10, 14); rail_layout.setSpacing(7)
        rail_mark = QLabel("J / 04"); rail_mark.setObjectName("railMark"); rail_layout.addWidget(rail_mark)
        rail_layout.addSpacing(12)
        for label in ('Home', 'Today', 'Desktop', 'Projects', 'Life', 'Research', 'Plugins'):
            button = QPushButton(label.upper()); button.setObjectName("railButton")
            button.clicked.connect(lambda checked=False, name=label: self.navigate(name)); rail_layout.addWidget(button)
        rail_layout.addStretch()
        manager = QPushButton("MANAGER"); manager.setObjectName("railButton"); manager.clicked.connect(self.open_manager_prompt); rail_layout.addWidget(manager)
        tools = QPushButton("COMMANDS"); tools.setObjectName("railButton"); tools.clicked.connect(self.open_command_palette); rail_layout.addWidget(tools)
        settings = QPushButton("SETTINGS"); settings.setObjectName("railButton"); settings.clicked.connect(self.open_settings); rail_layout.addWidget(settings)
        about = QPushButton("ABOUT"); about.setObjectName("railButton"); about.clicked.connect(self.open_about); rail_layout.addWidget(about)
        body.addWidget(rail)

        workspace = self._panel(); workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_stack = QStackedWidget(); workspace_layout.addWidget(self.workspace_stack)
        chat_page = QWidget(); rv = QVBoxLayout(chat_page)
        rv.setContentsMargins(22, 20, 22, 22); rv.setSpacing(12)
        title_row = QHBoxLayout(); workspace_title = QLabel("CONVERSATION"); workspace_title.setObjectName("section")
        self.mode_selector = QComboBox()
        for label, value in (("AUTO INTELLIGENCE", "auto"), ("FAST CHAT", "chat"),
                             ("GROUNDED RESEARCH", "deep_search"), ("REFLECTION", "reflection")):
            self.mode_selector.addItem(label, value)
        self.mode_selector.currentIndexChanged.connect(lambda: self.set_chat_mode(str(self.mode_selector.currentData())))
        title_row.addWidget(workspace_title); title_row.addStretch(); title_row.addWidget(self.mode_selector)
        rv.addLayout(title_row)
        self.chat = QTextEdit(); self.chat.setReadOnly(True); self.chat.setObjectName("chat"); rv.addWidget(self.chat, 1)
        input_row = QHBoxLayout(); input_row.setSpacing(10)
        self.input = QLineEdit(); self.input.setPlaceholderText("Ask JARVIS anything…"); self.input.setMinimumHeight(50)
        self.input.returnPressed.connect(self.send)
        self.mic = QPushButton("● TALK"); self.mic.setObjectName("mic"); self.mic.clicked.connect(self.toggle_recording)
        send = QPushButton("SEND  →"); send.setObjectName("primary"); send.clicked.connect(self.send)
        input_row.addWidget(self.input, 1); input_row.addWidget(self.mic); input_row.addWidget(send); rv.addLayout(input_row)
        self.workspace_stack.addWidget(chat_page)
        self.desktop_page = self._build_desktop_page(); self.workspace_stack.addWidget(self.desktop_page)
        body.addWidget(workspace, 1)

        focus = self._panel(); self.focus_panel = focus; focus.setFixedWidth(294); fv = QVBoxLayout(focus)
        fv.setContentsMargins(16, 18, 16, 16); fv.setSpacing(10)
        focus_title = QLabel("AMBIENT CORE"); focus_title.setObjectName("section"); fv.addWidget(focus_title)
        self.reactor = Reactor()
        self.reactor.set_visual_mode(load_config()["interface"].get("visual_mode", "hybrid"))
        fv.addWidget(self.reactor, 0, Qt.AlignmentFlag.AlignCenter)
        self.core_label = QLabel("LISTENING LAYER ONLINE"); self.core_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.core_label.setObjectName("corelabel")
        fv.addWidget(self.core_label)
        self.waveform = AudioWaveform(); fv.addWidget(self.waveform)
        voice_hint = QLabel("Speak naturally  /  silence sends")
        voice_hint.setObjectName("hint"); voice_hint.setWordWrap(True); voice_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fv.addWidget(voice_hint)
        fv.addStretch()
        tasks = QPushButton("DESKTOP CONTROL"); tasks.clicked.connect(self.open_task_studio); fv.addWidget(tasks)
        stop = QPushButton("EMERGENCY STOP"); stop.setObjectName("danger"); stop.clicked.connect(self.stop_task); fv.addWidget(stop)
        body.addWidget(focus)
        self.memory_list = QListWidget(); self.memory_list.hide()
        self.set_chat_mode("auto")

    def navigate(self, name):
        if name == 'Home': self.workspace_stack.setCurrentIndex(0); self.set_chat_mode('auto')
        elif name == 'Today': self.open_today()
        elif name == 'Desktop': self.workspace_stack.setCurrentIndex(1); self._refresh_desktop_context()
        elif name == 'Voice': self.toggle_recording()
        elif name == 'Plugins': self.open_plugins()
        elif name in ('Projects', 'Life') and not plugin_enabled('project_manager'):
            QMessageBox.information(self, "Plugin disabled", "Enable Project & Life Manager in PLUGINS first.")
        elif name == 'Life': WorkspaceDialog('Life', self).exec()
        else: WorkspaceDialog(name,self).exec()

    def _build_desktop_page(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 22); layout.setSpacing(12)
        title = QHBoxLayout(); label = QLabel("DESKTOP CONTROL"); label.setObjectName("section")
        self.desktop_state = QLabel("● OBSERVATION ACTIVE"); self.desktop_state.setObjectName("online")
        title.addWidget(label); title.addStretch(); title.addWidget(self.desktop_state); layout.addLayout(title)
        context_card = QFrame(); context_card.setObjectName("dataCard"); context_layout = QVBoxLayout(context_card)
        self.screen_context = QLabel("Reading active window…"); self.screen_context.setWordWrap(True)
        self.screen_context.setObjectName("dataValue"); context_layout.addWidget(QLabel("LIVE SCREEN CONTEXT"))
        context_layout.addWidget(self.screen_context); layout.addWidget(context_card)
        info = QLabel(
            "JARVIS observes transient window metadata while Desktop Control is enabled. "
            "Screenshots are not stored. Sensitive keyboard, mouse, sharing and publishing actions always need approval."
        )
        info.setObjectName("hint"); info.setWordWrap(True); layout.addWidget(info)
        row = QHBoxLayout(); build = QPushButton("BUILD TASK PLAN"); build.setObjectName("primary")
        build.clicked.connect(self.open_task_studio)
        stop = QPushButton("EMERGENCY STOP  CTRL+SHIFT+Q"); stop.setObjectName("danger"); stop.clicked.connect(self.stop_task)
        row.addWidget(build); row.addWidget(stop); layout.addLayout(row)
        layout.addWidget(self._section("RECENT ACTION AUDIT"))
        self.desktop_audit = QListWidget(); layout.addWidget(self.desktop_audit, 1)
        return page

    def _refresh_desktop_context(self):
        if not hasattr(self, "screen_context"):
            return
        if hasattr(self, "workspace_stack") and self.workspace_stack.currentWidget() is not self.desktop_page:
            return
        cfg = load_config()
        enabled = bool(cfg["desktop"].get("enabled") and cfg["desktop"].get("screen_observation", True))
        self.desktop_state.setText("● OBSERVATION ACTIVE" if enabled else "○ OBSERVATION OFF")
        if not enabled:
            self.screen_context.setText("Enable Desktop Control in Settings or Plugins.")
            return
        if self._desktop_refresh_pending:
            return
        self._desktop_refresh_pending = True
        self._task(desktop_context_data, (), self._desktop_context_ready, self._desktop_context_failed)

    def _desktop_context_ready(self, result):
        self._desktop_refresh_pending = False
        data, actions = result
        self.screen_context.setText(f"ACTIVE WINDOW  /  {data['active_window']}\nDISPLAY  /  {data['display']}")
        self.desktop_audit.clear()
        for created, action, detail, status in actions:
            self.desktop_audit.addItem(f"{created}  /  {action}  /  {status}  /  {detail}")

    def _desktop_context_failed(self, _error):
        self._desktop_refresh_pending = False
        self.screen_context.setText("Desktop context is temporarily unavailable.")

    def _change_context(self):
        mode = str(self.context_selector.currentData())
        cfg = load_config(); cfg["assistant"]["active_mode"] = mode; save_config(cfg)
        self.client.clear()
        self.append("SYSTEM", f"{mode.title()} context active. Memory and conversation retrieval now use this workspace.")

    def apply_window_mode(self, mode: str):
        if mode not in ("normal", "fullscreen", "floating"):
            return
        cfg = load_config(); cfg["interface"]["last_window_mode"] = mode; save_config(cfg)
        if mode == "fullscreen":
            self.rail.show(); self.focus_panel.show(); self.showFullScreen()
        elif mode == "floating":
            if self.isFullScreen(): self.showNormal()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.rail.hide(); self.focus_panel.hide(); self.setMinimumSize(520, 560); self.resize(560, 680); self.show()
        else:
            if self.isFullScreen(): self.showNormal()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.setMinimumSize(920, 640); self.rail.show(); self.focus_panel.show(); self.resize(1240, 800); self.show()

    def _install_emergency_stop(self):
        self.local_stop_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        self.local_stop_shortcut.activated.connect(self.stop_task)
        try:
            from pynput import keyboard
            self.global_hotkey = keyboard.GlobalHotKeys({"<ctrl>+<shift>+q": self.task_executor.cancel})
            self.global_hotkey.start()
        except Exception:
            self.global_hotkey = None

    def _install_productivity_shortcuts(self):
        self.palette_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.palette_shortcut.activated.connect(self.open_command_palette)
        self.interrupt_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.interrupt_shortcut.activated.connect(self.interrupt_voice)

    def toggle_visual_mode(self):
        modes = ("hybrid", "face", "core")
        current = self.reactor.visual_mode
        mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else "hybrid"
        self.reactor.set_visual_mode(mode)
        cfg = load_config(); cfg["interface"]["visual_mode"] = mode; save_config(cfg)
        if hasattr(self, "visual_button"):
            self.visual_button.setText({"hybrid": "CORE  ◈  HUD FACE", "face": "HUD FACE", "core": "REACTOR CORE"}[mode])

    def _panel(self):
        frame = QFrame(); frame.setObjectName("panel")
        shadow = QGraphicsDropShadowEffect(frame); shadow.setBlurRadius(35); shadow.setColor(QColor(255, 145, 24, 42)); frame.setGraphicsEffect(shadow)
        return frame

    def _section(self, text):
        label = QLabel(text); label.setObjectName("section"); return label

    def _start_timers(self):
        timer = QTimer(self); timer.timeout.connect(self.update_clock); timer.start(1000); self.update_clock()
        self.context_timer = QTimer(self); self.context_timer.timeout.connect(self._refresh_desktop_context)
        self.context_timer.start(max(1, int(load_config()["desktop"].get("screen_interval_seconds", 2))) * 1000)
        self.recovery_timer = QTimer(self); self.recovery_timer.timeout.connect(self._save_recovery)
        self.recovery_timer.start(5000)

    def update_clock(self):
        self.clock.setText(datetime.now().strftime("%H:%M"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "boot"):
            self.boot.setGeometry(self.centralWidget().rect())

    def _first_run(self):
        self.refresh_memory()
        if self.recovery_state:
            self.input.setText(str(self.recovery_state.get("draft", "")))
            self.set_chat_mode(str(self.recovery_state.get("chat_mode", "auto")))
            recovered_context = str(self.recovery_state.get("context", ""))
            recovered_index = self.context_selector.findData(recovered_context)
            if recovered_index >= 0:
                self.context_selector.setCurrentIndex(recovered_index)
            self.append("SYSTEM", "Recovered the workspace state from an interrupted session.")
        for message in recent_messages(10):
            self.append("YOU" if message["role"] == "user" else "JARVIS", message["content"])
        if not get_secret("gemini_api_key"):
            self.status.setText("● GEMINI SETUP REQUIRED")
            if self.open_api_key_setup():
                self._gemini_ready("connected")
            else:
                self.append("SYSTEM", "Gemini is not connected. Open SETTINGS → API key setup when ready.")
                self._offer_first_run_diagnostics()
                self._sync_always_listener()
        else:
            self.status.setText("● CHECKING GEMINI")
            self._task(validate_gemini_key, (get_secret("gemini_api_key"),),
                       self._gemini_ready, self._gemini_check_failed)

    def _gemini_ready(self, _message):
        self.append("JARVIS", "Ready. Type a message or speak naturally.")
        self.status.setText("● READY")
        self._sync_always_listener()
        cfg = load_config()
        if plugin_enabled("weather"):
            self._task(prefetch_weather, (), lambda _result: None, lambda _error: None)
        if cfg.get("updates", {}).get("automatic_check", True):
            self._task(check_for_updates, (), self._update_checked, lambda _error: None)
        self._offer_first_run_diagnostics()
        greeting = quick_reply("hi jarvis", cfg["assistant"]["name"], cfg["assistant"].get("user_name", ""))
        if cfg["voice"].get("speak_replies") and greeting:
            self._task(
                synthesize,
                (greeting, cfg["voice"].get("british_voice", "en-GB-ThomasNeural"),
                 cfg["voice"].get("speech_rate", 0), cfg["voice"].get("speech_pitch", 0)),
                lambda _path: None, lambda _error: None,
            )

    def _offer_first_run_diagnostics(self):
        if not load_config().get("onboarding", {}).get("diagnostics_run", False):
            QTimer.singleShot(350, self.open_diagnostics)

    def _update_checked(self, result):
        if result.get("available"):
            self.append("SYSTEM", f"JARVIS {result.get('latest')} is available in the configured update channel.")

    def _gemini_check_failed(self, error):
        self.append("SYSTEM", error)
        self.status.setText("● GEMINI NEEDS ATTENTION")
        if QMessageBox.question(self, "Gemini is not connected",
                                str(error) + "\n\nOpen Gemini Key Setup now?") == QMessageBox.StandardButton.Yes:
            if self.open_api_key_setup():
                self._gemini_ready("connected")
        self._sync_always_listener()

    def append(self, speaker: str, text: str):
        color = "#FFB547" if speaker == "JARVIS" else "#FFE0A3" if speaker == "YOU" else "#9B876C"
        safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self.chat.append(f'<div style="margin:8px 0"><b style="color:{color}">{speaker} //</b><br>{safe}</div>')

    def set_chat_mode(self, mode: str):
        allowed = ("auto", "chat", "deep_search", "reflection")
        self.chat_mode = mode if mode in allowed else "auto"
        if hasattr(self, "mode_selector") and self.mode_selector.currentData() != self.chat_mode:
            index = self.mode_selector.findData(self.chat_mode)
            self.mode_selector.setCurrentIndex(max(0, index))
        labels = {
            "auto": ("AUTO READY", "Ask naturally — JARVIS chooses the right mode…"),
            "chat": ("FAST CHAT READY", "Ask JARVIS…"),
            "deep_search": ("GROUNDED DEEP SEARCH READY", "Research with current sources…"),
            "reflection": ("REFLECTION MODE READY", "Analyse a difficult decision…"),
        }
        status, placeholder = labels[self.chat_mode]
        self.status.setText("● " + status); self.input.setPlaceholderText(placeholder)

    def send(self):
        text = self.input.text().strip()
        if not text: return
        self.input.clear(); self.append("YOU", text)
        handled, result = handle_memory_command(text)
        if handled:
            if result == "__CONFIRM_DELETE_ALL_MEMORY__":
                if QMessageBox.question(self, "Delete all memories?", "This permanently deletes JARVIS long-term memory.") == QMessageBox.StandardButton.Yes:
                    delete_all(); result = "All long-term memories were deleted."
                else: result = "Memory deletion cancelled."
            self.append("JARVIS", result); self.refresh_memory(); return
        cfg = load_config()
        local = (quick_reply(text, cfg["assistant"]["name"], cfg["assistant"].get("user_name", ""))
                 if cfg["assistant"].get("quick_local_replies", True) else None)
        local = local or local_core_response(text)
        if local:
            self._local_answer(text, local); return
        if is_weather_query(text) and plugin_enabled("weather"):
            self._stop_always_listener(); self.reactor.set_state("THINKING")
            self.status.setText("● READING LIVE WEATHER")
            self._task(weather_report, (requested_location(text),),
                       lambda answer: self._local_answer(text, answer)); return
        if not get_secret("gemini_api_key"):
            self.status.setText("● GEMINI SETUP REQUIRED")
            if not self.open_api_key_setup():
                return
        self._stop_always_listener()
        self.reactor.set_state("THINKING")
        self._active_mode = route_mode(text) if self.chat_mode == "auto" else self.chat_mode
        state = "DEEP SEARCHING" if self._active_mode == "deep_search" else "REFLECTING" if self._active_mode == "reflection" else "PROCESSING"
        self.status.setText("● " + state)
        self._task(self.client.chat, (text, self._active_mode), self._answer)

    def _local_answer(self, user_text: str, answer: str):
        self.client.record_exchange(user_text, str(answer))
        self._answer(str(answer))

    def _answer(self, answer):
        if self._active_mode == 'deep_search':
            save_record('Research', self.client.history[-2]['content'][:120] if len(self.client.history)>1 else 'Research', str(answer))
        self.append("JARVIS", answer); self.reactor.set_state("ONLINE"); self.status.setText("● READY")
        if load_config()["voice"]["speak_replies"]:
            self._stop_always_listener()
            voice_cfg = load_config()["voice"]
            voice = voice_cfg.get("british_voice", "en-GB-ThomasNeural")
            self._task(synthesize, (str(answer), voice, voice_cfg.get("speech_rate", 0),
                                    voice_cfg.get("speech_pitch", 0)), self._play_voice, self._voice_failed)
        else:
            QTimer.singleShot(300, self._sync_always_listener)

    def _failed(self, error):
        self.append("SYSTEM", error); self.reactor.set_state("ERROR"); self.status.setText("● CHECK MESSAGE")
        QTimer.singleShot(500, self._sync_always_listener)

    def _task(self, function, args, callback, error_callback=None):
        thread = QThread(self); task = Task(function, *args); task.moveToThread(thread)
        thread.started.connect(task.run); task.done.connect(callback); task.failed.connect(error_callback or self._failed)
        task.done.connect(thread.quit); task.failed.connect(thread.quit); thread.finished.connect(task.deleteLater)
        thread.finished.connect(thread.deleteLater); self.threads.append((thread, task)); thread.finished.connect(lambda: self.threads.remove((thread, task)) if (thread, task) in self.threads else None)
        thread.start()

    def _play_voice(self, path):
        self._stop_always_listener()
        if self.media_player is None:
            self.audio_output = QAudioOutput(self)
            self.media_player = QMediaPlayer(self); self.media_player.setAudioOutput(self.audio_output)
            self.media_player.mediaStatusChanged.connect(self._media_status)
        self.audio_output.setVolume(float(load_config()["voice"].get("speech_volume", 90)) / 100.0)
        self._remove_voice_file(); self._voice_file = str(path)
        self.media_player.setSource(QUrl.fromLocalFile(self._voice_file)); self.media_player.play()

    def _media_status(self, status):
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self._remove_voice_file()
            QTimer.singleShot(300, self._sync_always_listener)

    def _remove_voice_file(self):
        path, self._voice_file = self._voice_file, ""
        if path:
            try:
                if not is_cached_audio(path):
                    __import__('pathlib').Path(path).unlink(missing_ok=True)
            except Exception: pass

    def _voice_failed(self, message):
        """Use an installed en-GB Windows voice when neural audio is offline."""
        self.append("SYSTEM", "Cinematic neural voice is unavailable; using the Windows voice temporarily. " + str(message))
        self.status.setText("● NEURAL VOICE OFFLINE")
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            if not hasattr(self, "tts"):
                self.tts = QTextToSpeech(self)
                self.tts.stateChanged.connect(self._tts_state_changed)
            for voice in self.tts.availableVoices():
                if voice.locale().name().lower().startswith("en_gb"):
                    self.tts.setVoice(voice); break
            latest = self.client.history[-1]["content"] if self.client.history else ""
            if latest: self.tts.say(str(latest))
        except Exception:
            self._sync_always_listener()

    def _tts_state_changed(self, state):
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            if state == QTextToSpeech.State.Ready:
                QTimer.singleShot(300, self._sync_always_listener)
        except Exception:
            pass

    def toggle_recording(self):
        if self.interrupt_voice():
            return
        if not self.always_listener or not self.always_listener.isRunning():
            self._start_listener(manual=True); return
        self.always_listener.force_capture()
        self.voice_session.accept(load_config()["voice"].get("wake_phrase", "hey jarvis"))
        self.mic.setText("■ CAPTURING"); self.status.setText("● SPEAK NOW")
        self.reactor.set_state("LISTENING")

    def interrupt_voice(self) -> bool:
        stopped = False
        if self.media_player is not None and self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.stop(); self._remove_voice_file(); stopped = True
        if hasattr(self, "tts"):
            try:
                from PyQt6.QtTextToSpeech import QTextToSpeech
                if self.tts.state() == QTextToSpeech.State.Speaking:
                    self.tts.stop(); stopped = True
            except Exception:
                pass
        if stopped:
            self.status.setText("● SPEECH INTERRUPTED"); QTimer.singleShot(200, self._sync_always_listener)
        return stopped

    def _sync_always_listener(self):
        cfg = load_config()["voice"]
        if not cfg.get("always_listening", True):
            self._stop_always_listener(); self.mic.setText("● TALK"); return
        if self.always_listener and self.always_listener.isRunning():
            return
        self._start_listener()

    def _start_listener(self, manual=False):
        cfg = load_config()["voice"]
        listener = AlwaysListener(cfg.get("input_device", ""), cfg.get("end_silence_ms", 550), self)
        listener.captured.connect(self._voice_captured)
        listener.activity.connect(self._always_activity)
        listener.level.connect(self._voice_level)
        listener.fault.connect(self._always_fault)
        listener.finished.connect(lambda: self._listener_finished(listener))
        self.always_listener = listener; listener.start(); self.mic.setText("● LISTENING")
        if manual:
            listener.force_capture()

    def _stop_always_listener(self):
        listener = self.always_listener
        if self.always_listener is listener:
            self.always_listener = None
        if listener and listener.isRunning():
            # Never wait for an audio thread on Qt's GUI thread. The old
            # implementation blocked the whole window for up to 1.5 seconds.
            listener.stop()
            if listener not in self.retired_listeners:
                self.retired_listeners.append(listener)

    def _listener_finished(self, listener):
        if self.always_listener is listener:
            self.always_listener = None
            self.mic.setText("● TALK")
        if listener in self.retired_listeners:
            self.retired_listeners.remove(listener)

    def _always_activity(self, message):
        self.status.setText("● " + str(message))
        active = any(word in str(message) for word in ("LISTENING", "DETECTED", "CAPTUR", "CALIBRAT"))
        self.reactor.set_state("LISTENING" if active else "ONLINE")

    def _voice_level(self, level):
        self.waveform.set_level(level)
        if level > .45:
            self.reactor.energy = min(1.0, .35 + float(level) * .7)

    def _always_fault(self, message):
        self.append("SYSTEM", message); self.status.setText("● MICROPHONE ATTENTION"); self.mic.setText("● TALK")

    def _voice_captured(self, pcm, sample_rate):
        self._stop_always_listener()
        self.mic.setText("◈ PROCESSING")
        self.reactor.set_state("THINKING")
        english_only = bool(load_config()["voice"].get("english_only", True))
        import time
        voice_cfg = load_config()["voice"]
        natural = voice_cfg.get("activation_mode", "natural") == "natural"
        self._pending_wake_required = not natural and time.monotonic() >= self.voice_session.until
        engine = voice_cfg.get("input_engine", "fast_free")
        if engine == "gemini" and not get_secret("gemini_api_key"):
            engine = "fast_free"
        if engine in ("fast_free", "offline"):
            self.status.setText("● FAST SPEECH RECOGNITION" if engine == "fast_free" else "● PRIVATE OFFLINE RECOGNITION")
            self._task(
                transcribe_fast_free if engine == "fast_free" else transcribe_offline,
                (bytes(pcm), int(sample_rate)),
                self._offline_transcript,
                self._voice_request_failed,
            )
            return
        self.status.setText("● GEMINI UNDERSTANDING VOICE")
        self._task(
            self.client.chat_audio,
            (bytes(pcm), int(sample_rate), self.chat_mode, english_only,
             self._pending_wake_required, voice_cfg.get("wake_phrase", "hey jarvis")),
            self._voice_answer,
            self._voice_request_failed,
        )

    def _offline_transcript(self, transcript):
        transcript = str(transcript).strip()
        if not transcript:
            self.status.setText("● NO CLEAR SPEECH"); self.reactor.set_state("ONLINE")
            QTimer.singleShot(500, self._sync_always_listener); return
        natural = load_config()["voice"].get("activation_mode", "natural") == "natural"
        accepted = self.voice_session.resolve(transcript, require_wake=not natural)
        self._pending_wake_required = False
        if accepted is None:
            self.status.setText("● STANDBY — SAY HEY JARVIS"); self.reactor.set_state("ONLINE")
            QTimer.singleShot(300, self._sync_always_listener); return
        if not accepted:
            accepted = "Hello Jarvis"
        self._process_voice_text(accepted)

    def _voice_request_failed(self, error):
        message = str(error)
        self.append("SYSTEM", message)
        self.reactor.set_state("ONLINE")
        self.mic.setText("● TALK")
        if "quota" in message.casefold() or "429" in message:
            self.status.setText("● VOICE COOLING DOWN — TEXT READY")
            QTimer.singleShot(8000, self._sync_always_listener)
        else:
            self.status.setText("● VOICE NEEDS ATTENTION")
            QTimer.singleShot(1000, self._sync_always_listener)

    def _voice_answer(self, result):
        status = str(result.get("status", ""))
        if status == "no_speech":
            self.status.setText("● NO CLEAR SPEECH"); self.reactor.set_state("ONLINE")
            QTimer.singleShot(500, self._sync_always_listener); return
        if status == "non_english":
            self.status.setText("● ENGLISH VOICE ONLY"); self.reactor.set_state("ONLINE")
            QTimer.singleShot(500, self._sync_always_listener); return
        if status == "standby":
            self.status.setText("● STANDBY — SAY HEY JARVIS"); self.reactor.set_state("ONLINE")
            QTimer.singleShot(300, self._sync_always_listener); return
        transcript = str(result.get("transcript", "Voice command"))
        natural = load_config()["voice"].get("activation_mode", "natural") == "natural"
        if self._pending_wake_required and not natural:
            self.voice_session.accept(load_config()["voice"].get("wake_phrase", "hey jarvis"))
            self._pending_wake_required = False
        if self.voice_session.resolve(transcript, require_wake=not natural) is None:
            self.status.setText('STANDBY'); self._sync_always_listener(); return
        self._process_voice_text(transcript, str(result.get("answer", "")))

    def _process_voice_text(self, transcript: str, prepared_answer: str = ""):
        transcript = str(transcript).strip()
        if not transcript:
            self._sync_always_listener(); return
        self.append("YOU", transcript)
        handled, memory_result = handle_memory_command(transcript)
        if handled:
            if memory_result == "__CONFIRM_DELETE_ALL_MEMORY__":
                if QMessageBox.question(self, "Delete all memories?",
                                        "This permanently deletes JARVIS long-term memory.") == QMessageBox.StandardButton.Yes:
                    delete_all(); memory_result = "All long-term memories were deleted."
                else:
                    memory_result = "Memory deletion cancelled."
            self.refresh_memory(); self._answer(memory_result); return
        cfg = load_config()
        local = (quick_reply(transcript, cfg["assistant"]["name"], cfg["assistant"].get("user_name", ""))
                 if cfg["assistant"].get("quick_local_replies", True) else None)
        local = local or local_core_response(transcript)
        if local:
            self._local_answer(transcript, local); return
        if is_weather_query(transcript) and plugin_enabled("weather"):
            self.status.setText("● READING LIVE WEATHER")
            self._task(weather_report, (requested_location(transcript),),
                       lambda answer: self._local_answer(transcript, answer)); return
        if prepared_answer:
            self.client.record_exchange(transcript, prepared_answer)
            self._answer(prepared_answer)
            return
        if not get_secret("gemini_api_key"):
            self.append("SYSTEM", "Speech recognition is working. Connect Gemini in Settings so I can answer that request.")
            self.status.setText("● SPEECH WORKS — GEMINI SETUP REQUIRED")
            self.reactor.set_state("ONLINE"); QTimer.singleShot(500, self._sync_always_listener); return
        self._active_mode = route_mode(transcript) if self.chat_mode == "auto" else self.chat_mode
        state = "DEEP SEARCHING" if self._active_mode == "deep_search" else "REFLECTING" if self._active_mode == "reflection" else "PROCESSING"
        self.status.setText("● " + state)
        self._task(self.client.chat, (transcript, self._active_mode), self._answer)

    def refresh_memory(self):
        self.memory_list.clear()
        for row in search("", 50): self.memory_list.addItem(f"{row['category'].upper()}  {row['value']}")

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.saved.connect(self._settings_saved)
        dialog.exec()

    def open_command_palette(self):
        actions = {
            "Home": lambda: self.navigate("Home"), "Today and Focus": self.open_today,
            "Desktop Control": lambda: self.navigate("Desktop"), "Projects": lambda: self.navigate("Projects"),
            "Life": lambda: self.navigate("Life"), "Deep Search": lambda: self.set_chat_mode("deep_search"),
            "Reflection": lambda: self.set_chat_mode("reflection"), "Plugin Manager": self.open_plugins,
            "Application Permissions": self.open_permissions, "System Diagnostics": self.open_diagnostics,
            "Performance Monitor": self.open_performance, "Sensitive Activity": self.open_activity,
            "Encrypted Backup": self.open_backup, "Memory": self.open_memory,
            "Manager Prompt": self.open_manager_prompt, "Settings": self.open_settings,
        }
        CommandPalette(actions, self).exec()

    def open_today(self): TodayDialog(self).exec()
    def open_permissions(self): PermissionsDialog(self.registry, self).exec()
    def open_diagnostics(self): DiagnosticsDialog(self.registry, self).exec()
    def open_performance(self): PerformanceDialog(self).exec()
    def open_activity(self): ActivityDialog(self).exec()
    def open_backup(self): BackupDialog(self).exec()

    def _settings_saved(self):
        voice_cfg = load_config()["voice"]
        self.voice_session = VoiceSession(
            voice_cfg["session_timeout"], voice_cfg["wake_phrase"], voice_cfg.get("wake_phrases"))
        self.append("SYSTEM", "Configuration secured and active.")
        self._sync_always_listener()

    def open_api_key_setup(self) -> bool:
        return ApiKeyDialog(self).exec() == QDialog.DialogCode.Accepted

    def open_about(self):
        QMessageBox.about(
            self,
            "About JARVIS V6",
            "<h2>JARVIS V6</h2>"
            "<p>Futuristic desktop intelligence and task-control system.</p>"
            "<p><b>Created by Reda Benyassek</b></p>"
            "<p>Copyright © 2026 Reda Benyassek. All rights reserved.</p>",
        )

    def open_memory(self):
        dialog = MemoryDialog(self); dialog.changed.connect(self.refresh_memory); dialog.exec()

    def open_plugins(self):
        dialog = PluginManagerDialog(self)
        dialog.changed.connect(lambda: self.append("SYSTEM", "Plugin permissions updated."))
        dialog.exec()

    def open_manager_prompt(self):
        ManagerPromptDialog(self).exec()

    def open_task_studio(self):
        cfg = load_config()
        if not cfg["desktop"].get("enabled"):
            QMessageBox.information(self, "Desktop Control disabled",
                "Enable the Desktop Control plugin in PLUGINS first.")
            return
        dialog = TaskStudio(self.registry, self); dialog.run_plan.connect(self.review_task); dialog.exec()

    def review_task(self, plan):
        try:
            reviewed = build_execution_plan("User-reviewed desktop task", plan, self.registry,
                                            load_config()["desktop"].get("max_steps", 20))
        except ValueError as exc:
            QMessageBox.warning(self, "Plan rejected", str(exc)); return
        summary = "\n".join(
            f"{i}. {step.label}: {step.value[:120]}" for i, step in enumerate(reviewed.steps, 1))
        approval_required = reviewed.requires_approval
        if approval_required:
            contains_sensitive = any(self.registry.actions[step.action].sensitive for step in plan)
            reason = (
                "This plan controls keyboard, mouse, files or private data."
                if contains_sensitive else
                "Your current permission profile confirms every desktop plan."
            )
            answer = QMessageBox.question(self, "Approve desktop plan?",
                summary + "\n\n" + reason + " After approval you have 3 seconds to focus the target window.")
            if answer != QMessageBox.StandardButton.Yes:
                self.append("SYSTEM", "Desktop plan cancelled before execution."); return
            delay = 3000
            self.append("SYSTEM", "Desktop plan approved. Execution begins in 3 seconds.")
        else:
            delay = 750
            self.append("SYSTEM", "Approved low-risk desktop plan queued.")
        self.reactor.set_state("THINKING")
        QTimer.singleShot(
            delay,
            lambda: self._task(
                self.task_executor.execute, (plan, None, approval_required), self._task_complete))

    def _task_complete(self, results):
        self.append("JARVIS", "Desktop task completed:\n" + "\n".join(results)); self.reactor.set_state("ONLINE")
        self._refresh_desktop_context()

    def stop_task(self):
        self.task_executor.cancel(); self.append("SYSTEM", "Stop requested. JARVIS will halt before the next step.")

    def closeEvent(self, event):
        self._save_recovery(clean_exit=True)
        self._stop_always_listener()
        for listener in list(self.retired_listeners):
            listener.stop(); listener.wait(600)
        if self.global_hotkey is not None:
            self.global_hotkey.stop()
        if self.media_player is not None:
            self.media_player.stop()
        self._remove_voice_file()
        event.accept()

    def _save_recovery(self, clean_exit=False):
        state = {"draft": self.input.text(), "chat_mode": self.chat_mode,
                 "context": self.context_selector.currentData(),
                 "window_mode": load_config()["interface"].get("last_window_mode", "normal")}
        signature = tuple(sorted(state.items()))
        if clean_exit:
            recovery.save(state, True); self._last_recovery_state = signature; return
        if signature == self._last_recovery_state or self._recovery_pending:
            return
        self._recovery_pending = True
        self._task(recovery.save, (state, False),
                   lambda _result: self._recovery_saved(signature), self._recovery_failed)

    def _recovery_saved(self, signature):
        self._last_recovery_state = signature; self._recovery_pending = False

    def _recovery_failed(self, _error):
        self._recovery_pending = False

    def _style(self):
        return f"""
        QMainWindow {{ background:{INK}; }}
        QWidget {{ background:transparent; color:#EDF1F4; font-family:'Segoe UI'; font-size:13px; }}
        QWidget#hudRoot {{ background:{INK}; }}
        #panel {{ background:rgba(12,12,11,232); border:1px solid rgba(255,255,255,30); border-radius:9px; }}
        #rail {{ background:rgba(9,9,8,242); border:1px solid rgba(255,255,255,22); border-radius:9px; }}
        #brand {{ color:#F5F3EE; font-size:25px; font-weight:650; letter-spacing:5px; }}
        #creator {{ color:#777570; font-size:9px; font-family:Consolas; letter-spacing:1px; }}
        #clock {{ color:#777570; padding:0 10px; }}
        #online {{ color:#E7E4DC; font-family:Consolas; font-weight:650; padding:7px 11px; background:rgba(255,255,255,9); border:1px solid rgba(255,255,255,30); border-radius:9px; }}
        #engine {{ color:#A5A29B; font-family:Consolas; font-size:10px; font-weight:650; padding:0 8px; letter-spacing:1px; }}
        #section {{ color:#E8E5DE; font-family:Consolas; font-size:10px; font-weight:650; letter-spacing:3px; padding:3px 2px 8px 2px; }}
        #data {{ color:#777570; font-family:Consolas; font-size:9px; letter-spacing:1px; }}
        #corelabel {{ color:#E7EBEF; font-family:Consolas; font-size:10px; font-weight:700; letter-spacing:3px; }}
        #hint {{ color:#777570; font-family:Consolas; font-size:10px; line-height:1.4; padding:8px; }}
        #keyStatus {{ color:#D9DEE3; font-weight:650; }}
        #dataCard {{ background:rgba(20,23,26,205); border:1px solid #343A40; border-radius:7px; }}
        #dataLabel {{ color:#89929B; font-family:Consolas; font-size:8px; }}
        #dataValue {{ color:#EDF1F4; font-family:Consolas; font-size:10px; font-weight:700; }}
        #chat {{ background:rgba(3,3,3,215); border:1px solid rgba(255,255,255,24); border-radius:7px; padding:20px; font-size:14px; }}
        QLineEdit, QPlainTextEdit, QComboBox, QListWidget {{ background:rgba(18,18,17,245); border:1px solid rgba(255,255,255,38); border-radius:7px; padding:10px; color:#EEECE6; selection-background-color:#76501D; }}
        QLineEdit:focus, QPlainTextEdit:focus {{ border:1px solid #AEB8C2; }}
        QPushButton {{ min-height:20px; background:rgba(255,255,255,7); color:#C9C6BE; border:1px solid rgba(255,255,255,35); border-radius:7px; padding:9px 14px; font-family:Consolas; font-weight:650; letter-spacing:1px; }}
        QPushButton:hover {{ background:rgba(255,255,255,15); border-color:rgba(255,255,255,80); color:#FFFFFF; }}
        QPushButton#railButton {{ text-align:left; background:transparent; border:none; color:#8E8B84; padding:10px 12px; }}
        QPushButton#railButton:hover {{ background:rgba(255,255,255,8); color:#F3F0E8; }}
        #railMark {{ color:#E5E9ED; font-family:Consolas; font-size:12px; font-weight:700; letter-spacing:2px; padding:8px 11px; }}
        QPushButton#mode {{ color:#A5ADB5; border-color:#343A40; }}
        QPushButton#mode:checked {{ background:rgba(44,49,54,230); border:1px solid #B9C2CA; color:#FFFFFF; }}
        QPushButton#primary {{ background:#E2E7EB; border-color:#FFFFFF; color:#111417; }}
        QPushButton#primary:hover {{ background:#FFFFFF; }}
        QPushButton#danger {{ color:#FFB3A7; border-color:#8A342A; background:rgba(65,18,13,220); }}
        QPushButton#danger:hover {{ color:#FFFFFF; border-color:#FF7666; background:rgba(125,35,25,235); }}
        QPushButton#mic {{ min-width:105px; }}
        QScrollBar:vertical {{ background:#111315; width:8px; margin:0; }}
        QScrollBar::handle:vertical {{ background:#444B52; min-height:30px; border-radius:3px; }}
        QScrollArea {{ border:none; background:transparent; }}
        QDialog {{ background:#080A0C; }} QDialog QLabel {{ color:#C9D0D6; }}
        #bootOverlay {{ background:#060606; }}
        #bootMark {{ color:#E3E8EC; font-family:Consolas; font-size:17px; font-weight:700; letter-spacing:4px; }}
        #bootStage {{ color:#F4F1EA; font-family:Consolas; font-size:13px; font-weight:650; letter-spacing:5px; }}
        #bootDetail {{ color:#686762; font-family:Consolas; font-size:9px; letter-spacing:2px; }}
        QProgressBar {{ background:#151514; border:none; border-radius:2px; height:3px; }}
        QProgressBar::chunk {{ background:#E3E8EC; border-radius:2px; }}
        """
