"""Окно Ampilight: сначала плата, потом управление лентой."""

from __future__ import annotations

import ctypes
import threading
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.camera import LaptopCamera
from app.detect import grade_picture, sample_perimeter
from app.engine import GridSampler, blend, compose_pixels, output_length, pack_colors
from app.flash import FlashJob
from app.sck import ScreenStream, display_list
from app.sender import FindThread, Sender, list_serial_ports
from app.theme import THEME
from app.tv import TvStream, grab_size
from app.wifi import WifiThread, current_ssid

UDP_PORT = 4210
COLOR_ORDER = "GRB"


def _split_sides(total: int) -> tuple[int, int, int, int]:
    """Слева, сверху, справа, снизу. Верх и низ длиннее боков, как на телевизоре."""
    total = max(0, int(total))
    side = max(0, round(total * 0.19))
    if side * 2 > total:
        side = total // 4
    left = right = side
    rest = total - left - right
    top = rest // 2
    bottom = rest - top
    return left, top, right, bottom


def apply_app_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setApplicationName("Ampilight")
    app.setOrganizationName("Ampilight")
    font = app.font()
    font.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
    font.setPointSize(13)
    app.setFont(font)
    app.setStyleSheet(THEME)


def _swatch_style(rgb: tuple[int, int, int], chosen: bool) -> str:
    red, green, blue = rgb
    border = "#ffd36a" if chosen else "#3a3d44"
    width = 3 if chosen else 1
    return (
        "QPushButton {"
        f"background: rgb({red},{green},{blue});"
        f"border: {width}px solid {border};"
        "border-radius: 8px; padding: 0;"
        "}"
        "QPushButton:checked {"
        f"background: rgb({red},{green},{blue});"
        "border: 3px solid #ffd36a;"
        "}"
    )


def screen_access() -> bool:
    try:
        core = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        core.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        core.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        if core.CGPreflightScreenCaptureAccess():
            return True
        return bool(core.CGRequestScreenCaptureAccess())
    except Exception:
        return True


class ColorBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.pixels = np.zeros((0, 3), dtype=np.uint8)
        self.setFixedHeight(28)

    def set_pixels(self, pixels: np.ndarray) -> None:
        self.pixels = pixels
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect().adjusted(0, 0, -1, -1)), 8, 8)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor("#0c0d10"))
        count = 0 if self.pixels.ndim != 2 else len(self.pixels)
        if count:
            width = self.width()
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(count):
                red, green, blue = self.pixels[index]
                x1 = int(index * width / count)
                x2 = int((index + 1) * width / count)
                painter.fillRect(
                    x1,
                    0,
                    max(1, x2 - x1),
                    self.height(),
                    QColor(int(red), int(green), int(blue)),
                )
        painter.setClipping(False)
        painter.setPen(QColor("#2a2d34"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)


class ScreenPreview(QWidget):
    """Кадр камеры. Четыре угла двигаются по отдельности: рамка может быть косой."""

    pointsChanged = pyqtSignal(object)
    _HANDLE = 18

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(220)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._image: QImage | None = None
        self._points: tuple[tuple[float, float], ...] | None = None
        self._drag: int | None = None
        self._before: tuple[tuple[float, float], ...] | None = None

    def set_image(self, rgb: np.ndarray) -> None:
        rgb = np.ascontiguousarray(rgb)
        height, width, _ = rgb.shape
        payload = rgb.tobytes()
        image = QImage(payload, width, height, width * 3, QImage.Format.Format_RGB888)
        self._image = image.copy()
        self.update()

    def set_points(self, points: tuple[tuple[float, float], ...] | None) -> None:
        self._points = None if points is None else tuple((float(x), float(y)) for x, y in points)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect().adjusted(0, 0, -1, -1)), 8, 8)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor("#0c0d10"))
        if self._image is None:
            painter.setPen(QColor("#8f918a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Камера включается…")
        else:
            fitted = self._fitted()
            painter.drawImage(fitted, self._image)
            corners = self._pixel_points()
            if corners is not None:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#0c0d10"), 4))
                painter.drawPolygon(QPolygonF(corners))
                painter.setPen(QPen(QColor("#ffd36a"), 2))
                painter.drawPolygon(QPolygonF(corners))
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor("#2a2d34"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        corners = self._pixel_points()
        if corners is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            for corner in corners:
                painter.setBrush(QColor("#0c0d10"))
                painter.drawEllipse(QRectF(corner.x() - 7, corner.y() - 7, 14, 14))
                painter.setBrush(QColor("#ffd36a"))
                painter.drawEllipse(QRectF(corner.x() - 4, corner.y() - 4, 8, 8))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._image is None:
            return
        index = self._hit(event.position())
        if index is None or self._points is None:
            return
        self._drag = index
        self._before = self._points
        self._move_point(index, self._norm(event.position()))
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._image is None:
            return
        if self._drag is None:
            self.setCursor(
                Qt.CursorShape.SizeAllCursor if self._hit(event.position()) is not None else Qt.CursorShape.ArrowCursor
            )
            return
        self._move_point(self._drag, self._norm(event.position()))
        self.update()
        if self._points is not None:
            self.pointsChanged.emit(self._points)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is None:
            return
        self._move_point(self._drag, self._norm(event.position()))
        self._drag = None
        self.update()
        if self._points is not None:
            self.pointsChanged.emit(self._points)
        event.accept()

    def _move_point(self, index: int, point: tuple[float, float]) -> None:
        if self._points is None:
            return
        points = list(self._points)
        points[index] = point
        self._points = tuple(points)

    def _hit(self, pos: QPointF) -> int | None:
        corners = self._pixel_points()
        if corners is None:
            return None
        best = None
        best_distance = self._HANDLE
        for index, corner in enumerate(corners):
            distance = ((pos.x() - corner.x()) ** 2 + (pos.y() - corner.y()) ** 2) ** 0.5
            if distance <= best_distance:
                best = index
                best_distance = distance
        return best

    def _pixel_points(self) -> list[QPointF] | None:
        if self._points is None or self._image is None:
            return None
        fitted = self._fitted()
        return [
            QPointF(fitted.x() + x * fitted.width(), fitted.y() + y * fitted.height())
            for x, y in self._points
        ]

    def _norm(self, pos: QPointF) -> tuple[float, float]:
        fitted = self._fitted()
        if self._image is None or fitted.width() < 1 or fitted.height() < 1:
            return (0.0, 0.0)
        return (
            min(max((pos.x() - fitted.x()) / fitted.width(), 0.0), 1.0),
            min(max((pos.y() - fitted.y()) / fitted.height(), 0.0), 1.0),
        )

    def _fitted(self) -> QRectF:
        assert self._image is not None
        bounds = QRectF(self.rect().adjusted(1, 1, -2, -2))
        scale = min(bounds.width() / self._image.width(), bounds.height() / self._image.height())
        width = self._image.width() * scale
        height = self._image.height() * scale
        return QRectF(
            bounds.x() + (bounds.width() - width) / 2,
            bounds.y() + (bounds.height() - height) / 2,
            width,
            height,
        )

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ampilight")
        self.setFixedWidth(420)
        self.frames_seen = 0
        self.last_mean = 0.0
        self.grab_error = ""
        self.transmitting = False
        self.play: str | None = None
        self._pending_play: str | None = None
        self._alive = True
        self._loop_started = False
        self._sampler = GridSampler()
        self._previous = None
        self._fps_marks: list[float] = []
        self._device_status = ""
        self._pin_touched = False
        self._finder: FindThread | None = None
        self._wifi: WifiThread | None = None
        self._saved_ssid = ""
        self._pending_flash = False
        self._ota_password = ""
        self._flash: FlashJob | None = None
        self._shot: dict = {}
        self._latest: dict | None = None
        self._latest_lock = threading.Lock()
        self._shown_seq = 0
        self._pump_fps = 0
        self._pending_display: int | None = None
        self._chase_index = 0
        self._chase_at = 0.0
        self._display_id = 0
        self.stream = ScreenStream()
        self.camera = LaptopCamera()
        self.camera.rgb.connect(self._on_camera_frame)
        self.camera.failed.connect(self._on_camera_failed)
        self.tv = TvStream()
        self.tv.rgb.connect(self._on_tv_frame)
        self.tv.failed.connect(self._on_camera_failed)
        self._tv_marks: list[float] = []
        self._manual_points: tuple[tuple[float, float], ...] | None = None
        self._firmware_leds = 0
        self._camera_status = ""
        self._camera_frames = 0
        self._camera_on_at = 0.0
        self._preview_at = 0.0
        self._camera_seq = 0
        self._pattern_seq = 0
        self._off_until = 0.0
        self._off_next = 0.0
        self._off_packet = b""
        self._pump: threading.Thread | None = None
        self.sender = Sender()
        self.sender.status.connect(self._on_device_status)
        self.sender.start()
        self._build()
        self._load()
        self._snapshot()

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_setup())
        self.control_page = self._build_control()
        self.control_scroll = QScrollArea()
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.control_scroll.setWidget(self.control_page)
        self.stack.addWidget(self.control_scroll)
        outer.addWidget(self.stack)

    def _build_setup(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        title = QLabel("Ampilight")
        title.setObjectName("title")
        subtitle = QLabel(
            "ESP32 входит в ту же Wi-Fi, что и этот компьютер. Первый раз прошивка идёт по USB, следующие — по этой сети."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        form.addWidget(title)
        form.addWidget(subtitle)

        board_row = QHBoxLayout()
        self.board_group = QButtonGroup(self)
        self.board_buttons: dict[str, QPushButton] = {}
        for board_id, label in (("nano-old", "Arduino Nano"), ("esp32", "ESP32")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.board_group.addButton(button)
            self.board_buttons[board_id] = button
            board_row.addWidget(button)
        self.board_buttons["esp32"].setChecked(True)
        self.board_group.buttonClicked.connect(lambda _b: self._board_changed())
        form.addLayout(board_row)

        form.addWidget(self._field("Количество диодов"))
        self.leds = QSpinBox()
        self.leds.setRange(1, 512)
        self.leds.setValue(90)
        form.addWidget(self.leds)

        form.addWidget(self._field("Пин данных"))
        self.pin = QSpinBox()
        self.pin.setRange(0, 40)
        self.pin.setValue(5)
        self.pin.valueChanged.connect(self._pin_edited)
        form.addWidget(self.pin)

        self.wifi_box = QWidget()
        wifi = QVBoxLayout(self.wifi_box)
        wifi.setContentsMargins(0, 0, 0, 0)
        wifi.setSpacing(8)
        wifi.addWidget(self._field("Сеть этого компьютера"))
        ssid_row = QHBoxLayout()
        self.ssid = QComboBox()
        self.ssid.addItem("Ищу сеть…")
        self.ssid.setEnabled(False)
        self.wifi_refresh = QPushButton("Обновить")
        self.wifi_refresh.setObjectName("ghost")
        self.wifi_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wifi_refresh.clicked.connect(self._scan_wifi)
        ssid_row.addWidget(self.ssid, 1)
        ssid_row.addWidget(self.wifi_refresh)
        wifi.addLayout(ssid_row)
        wifi_hint = QLabel("Плата подключится сюда. На телевизоре это будет сеть телевизора.")
        wifi_hint.setObjectName("hint")
        wifi_hint.setWordWrap(True)
        wifi.addWidget(wifi_hint)
        wifi.addWidget(self._field("Пароль Wi-Fi"))
        self.wifi_password = QLineEdit()
        self.wifi_password.setPlaceholderText("Пароль этой сети")
        self.wifi_password.setEchoMode(QLineEdit.EchoMode.Password)
        wifi.addWidget(self.wifi_password)
        form.addWidget(self.wifi_box)

        form.addWidget(self._field("USB для прошивки"))
        port_row = QHBoxLayout()
        self.port = QComboBox()
        self.refresh_ports = QPushButton("Обновить")
        self.refresh_ports.setObjectName("ghost")
        self.refresh_ports.clicked.connect(lambda: self._fill_ports())
        port_row.addWidget(self.port, 1)
        port_row.addWidget(self.refresh_ports)
        form.addLayout(port_row)
        usb_hint = QLabel("Если USB нет, а плата уже в Wi-Fi, «Прошить» отправит программу по сети.")
        usb_hint.setObjectName("hint")
        usb_hint.setWordWrap(True)
        form.addWidget(usb_hint)

        self.flash_button = QPushButton("Прошить")
        self.flash_button.setObjectName("startButton")
        self.flash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.flash_button.clicked.connect(self._flash_clicked)
        form.addWidget(self.flash_button)

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(128)
        self.log.setPlaceholderText("Здесь будет ход прошивки")
        form.addWidget(self.log)

        self.setup_status = QLabel("")
        self.setup_status.setObjectName("hint")
        self.setup_status.setWordWrap(True)
        form.addWidget(self.setup_status)

        skip = QPushButton("Лента уже прошита")
        skip.setObjectName("ghost")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.clicked.connect(self._show_control)
        form.addWidget(skip)
        return page

    def _build_control(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        back = QPushButton("К плате")
        back.setObjectName("ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self._show_setup)
        form.addWidget(back, alignment=Qt.AlignmentFlag.AlignLeft)

        self.control_title = QLabel("Лента")
        self.control_title.setObjectName("title")
        form.addWidget(self.control_title)

        self.preview = ScreenPreview()
        self.preview.hide()
        self.preview.pointsChanged.connect(self._frame_drawn)
        form.addWidget(self.preview)
        self.frame_hint = QLabel(
            "Каждую жёлтую точку сдвинь на свой угол телевизора. Рамка может быть косой."
        )
        self.frame_hint.setObjectName("hint")
        self.frame_hint.setWordWrap(True)
        self.frame_hint.hide()
        form.addWidget(self.frame_hint)

        form.addWidget(self._build_sides())

        self.camera_box = self._build_camera_tools()
        self.camera_box.hide()
        form.addWidget(self.camera_box)

        self.device_box = QWidget()
        device_form = QVBoxLayout(self.device_box)
        device_form.setContentsMargins(0, 0, 0, 0)
        device_form.setSpacing(8)
        device_form.addWidget(self._field("Плата в Wi-Fi"))
        self.devices = QComboBox()
        self.devices.addItem("Ищу плату…", "")
        self.devices.currentIndexChanged.connect(self._device_picked)
        device_form.addWidget(self.devices)
        form.addWidget(self.device_box)

        form.addWidget(self._field("Что сейчас на ленте"))
        self.bar = ColorBar()
        form.addWidget(self.bar)

        self.play_group = QButtonGroup(self)
        self.play_group.setExclusive(True)
        self.play_buttons: dict[str, QPushButton] = {}
        for mode, label, primary in (
            ("screen", "С экрана", True),
            ("camera", "С камеры", False),
            ("tv", "С телевизора (по adb)", False),
            ("chase", "Красный огонёк по диодам", False),
            ("all", "Все диоды", False),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if primary:
                button.setObjectName("startButton")
            self.play_group.addButton(button)
            self.play_buttons[mode] = button
            button.clicked.connect(lambda _checked=False, name=mode: self._start(name))
            form.addWidget(button)

        stop = QPushButton("Остановить")
        stop.setObjectName("ghost")
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.clicked.connect(self._stop)
        form.addWidget(stop)

        self.color_box = QWidget()
        colors = QVBoxLayout(self.color_box)
        colors.setContentsMargins(0, 0, 0, 0)
        colors.setSpacing(8)
        colors.addWidget(self._field("Цвет"))
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(8)
        self._fill_color = (255, 255, 255)
        self._fill_name = "белый"
        self._swatches: list[tuple[QPushButton, tuple[int, int, int], str]] = []
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        for rgb, color_name in (
            ((255, 255, 255), "белый"),
            ((255, 0, 0), "красный"),
            ((255, 120, 0), "оранжевый"),
            ((255, 210, 0), "жёлтый"),
            ((0, 200, 70), "зелёный"),
            ((0, 180, 255), "голубой"),
            ((70, 90, 255), "синий"),
            ((190, 0, 255), "фиолетовый"),
        ):
            swatch = QPushButton()
            swatch.setFixedSize(32, 32)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setCheckable(True)
            swatch.setStyleSheet(_swatch_style(rgb, rgb == self._fill_color))
            if rgb == self._fill_color:
                swatch.setChecked(True)
            self.color_group.addButton(swatch)
            swatch.clicked.connect(
                lambda _checked=False, color=rgb, label=color_name: self._pick_color(color, label)
            )
            self._swatches.append((swatch, rgb, color_name))
            swatch_row.addWidget(swatch)
        swatch_row.addStretch(1)
        colors.addLayout(swatch_row)
        self.color_name = QLabel("Сейчас белый")
        self.color_name.setObjectName("hint")
        colors.addWidget(self.color_name)
        self.color_box.hide()
        form.addWidget(self.color_box)

        self.find_button = QPushButton("Найти ESP32")
        self.find_button.setObjectName("ghost")
        self.find_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_button.clicked.connect(self._discover)
        form.addWidget(self.find_button)

        self.status = QLabel("Выбери, что включить на ленте.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        return page

    def _ssid(self) -> str:
        text = self.ssid.currentText().strip()
        if text in {"", "Ищу сети…", "Ищу сеть…", "Сети не найдены", "Компьютер не в Wi-Fi"}:
            return ""
        return text

    def _scan_wifi(self) -> None:
        if self._wifi is not None and self._wifi.isRunning():
            return
        self.wifi_refresh.setEnabled(False)
        self.ssid.blockSignals(True)
        self.ssid.clear()
        self.ssid.addItem("Ищу сеть…")
        self.ssid.blockSignals(False)
        self._wifi = WifiThread()
        self._wifi.found.connect(self._wifi_found)
        self._wifi.start()

    def _wifi_found(self, result) -> None:
        self.wifi_refresh.setEnabled(True)
        self.ssid.blockSignals(True)
        self.ssid.clear()
        if isinstance(result, Exception) or not result:
            self.ssid.addItem("Компьютер не в Wi-Fi")
            detail = str(result) if isinstance(result, Exception) else "Подключи этот компьютер к Wi-Fi и нажми Обновить."
            if self._flash is None or not self._flash.isRunning():
                self._device_status = detail
        else:
            self.ssid.addItem(result[0])
            if self._flash is None or not self._flash.isRunning():
                self._device_status = ""
        self.ssid.blockSignals(False)
        self._render_status()

    def _build_camera_tools(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.bright_slider = self._tune_slider(layout, "Яркость", 40, 160, 100, "cam_brightness")
        self.contrast_slider = self._tune_slider(layout, "Контраст", 40, 200, 120, "cam_contrast")
        self.depth_slider = self._tune_slider(layout, "От края", 5, 40, 20, "cam_depth")
        self.tv_fps_slider = self._tune_slider(layout, "Кадров с ТВ", 2, 12, 6, "tv_fps", " к/с")
        note = QLabel("Цвет берётся полосой у края экрана, не из середины. Глубже — больше кадра.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.camera_reverse = QCheckBox("Обратный ход ленты")
        self.camera_reverse.toggled.connect(lambda _checked: self._camera_tune_changed())
        layout.addWidget(self.camera_reverse)
        self.camera_mirror = QCheckBox("Зеркальное отображение")
        self.camera_mirror.setChecked(True)
        self.camera_mirror.toggled.connect(lambda _checked: self._camera_tune_changed())
        layout.addWidget(self.camera_mirror)
        return box

    def _tune_slider(
        self,
        layout: QVBoxLayout,
        title: str,
        low: int,
        high: int,
        default: int,
        key: str,
        suffix: str = "%",
    ) -> QSlider:
        row = QHBoxLayout()
        row.addWidget(self._field(title))
        value = QLabel(f"{default}{suffix}")
        value.setObjectName("count")
        row.addStretch(1)
        row.addWidget(value)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(default)
        slider.valueChanged.connect(
            lambda number, label=value, name=key, end=suffix: self._slider_moved(label, name, number, end)
        )
        slider.setProperty("caption", value)
        slider.setProperty("suffix", suffix)
        layout.addWidget(slider)
        return slider

    def _slider_moved(self, label: QLabel, key: str, number: int, suffix: str = "%") -> None:
        label.setText(f"{number}{suffix}")
        QSettings().setValue(key, number)
        self._previous = None
        if key == "tv_fps" and self.play == "tv" and self.transmitting:
            self._restart_tv()

    def _camera_tune_changed(self) -> None:
        settings = QSettings()
        settings.setValue("cam_reverse", self.camera_reverse.isChecked())
        settings.setValue("cam_mirror", self.camera_mirror.isChecked())
        self._previous = None

    def _build_sides(self) -> QWidget:
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.side_boxes: dict[str, QSpinBox] = {}
        for key, label, row, column in (
            ("top", "Сверху", 0, 1),
            ("left", "Слева", 1, 0),
            ("right", "Справа", 1, 2),
            ("bottom", "Снизу", 2, 1),
        ):
            column_box = QWidget()
            column_layout = QVBoxLayout(column_box)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(2)
            column_layout.addWidget(self._field(label))
            spin = QSpinBox()
            spin.setRange(0, 300)
            spin.setValue(0)
            spin.valueChanged.connect(self._sides_changed)
            self.side_boxes[key] = spin
            column_layout.addWidget(spin)
            grid.addWidget(column_box, row, column)
        self.side_total = QLabel("Всего 0")
        self.side_total.setObjectName("hint")
        self.side_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.side_total, 1, 1)
        return box

    def _side_counts(self) -> tuple[int, int, int, int]:
        def value(key: str) -> int:
            box = self.side_boxes.get(key)
            return 0 if box is None else int(box.value())
        return value("left"), value("top"), value("right"), value("bottom")

    def _sides_changed(self) -> None:
        left, top, right, bottom = self._side_counts()
        total = left + top + right + bottom
        self.side_total.setText(f"Всего {total}")
        settings = QSettings()
        settings.setValue("side_left", left)
        settings.setValue("side_top", top)
        settings.setValue("side_right", right)
        settings.setValue("side_bottom", bottom)
        self._previous = None
        if self.play == "tv" and self.transmitting:
            self._restart_tv()
        if self.stack.currentIndex() == 1:
            name = "ESP32" if self._is_esp() else "Arduino Nano"
            self.control_title.setText(f"{name} · {total} диодов")

    def _field(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("field")
        return label

    def _load(self) -> None:
        settings = QSettings()
        count = int(settings.value("leds", 90))
        self.leds.setValue(count)
        saved_side = settings.value("side_left", None)
        if saved_side is None:
            left, top, right, bottom = _split_sides(count)
        else:
            left = int(settings.value("side_left", 0))
            top = int(settings.value("side_top", 0))
            right = int(settings.value("side_right", 0))
            bottom = int(settings.value("side_bottom", 0))
        for key, number in (("left", left), ("top", top), ("right", right), ("bottom", bottom)):
            box = self.side_boxes[key]
            box.blockSignals(True)
            box.setValue(number)
            box.blockSignals(False)
        self.side_total.setText(f"Всего {left + top + right + bottom}")
        self._firmware_leds = int(settings.value("firmware_leds", 0) or 0)
        for slider, key, default in (
            (self.bright_slider, "cam_brightness", 100),
            (self.contrast_slider, "cam_contrast", 120),
            (self.depth_slider, "cam_depth", 20),
            (self.tv_fps_slider, "tv_fps", 6),
        ):
            slider.blockSignals(True)
            slider.setValue(int(settings.value(key, default)))
            slider.blockSignals(False)
            caption = slider.property("caption")
            if isinstance(caption, QLabel):
                caption.setText(f"{slider.value()}{slider.property('suffix') or '%'}")
        self.camera_reverse.blockSignals(True)
        self.camera_reverse.setChecked(str(settings.value("cam_reverse", "false")).lower() in {"true", "1"})
        self.camera_reverse.blockSignals(False)
        self.camera_mirror.blockSignals(True)
        self.camera_mirror.setChecked(str(settings.value("cam_mirror", True)).lower() in {"true", "1"})
        self.camera_mirror.blockSignals(False)
        board = str(settings.value("board", "esp32"))
        self.board_buttons.get(board, self.board_buttons["esp32"]).setChecked(True)
        self.pin.blockSignals(True)
        default_pin = 5 if board == "esp32" else 6
        self.pin.setValue(int(settings.value("pin", default_pin)))
        self.pin.blockSignals(False)
        self._saved_ssid = str(settings.value("ssid", ""))
        self._ota_password = str(settings.value("ota_password", ""))
        self.wifi_password.setText(str(settings.value("wifi_password", "")))
        self.host = QLineEdit()
        self.host.setText(str(settings.value("host", "")))
        self._fill_ports(str(settings.value("port", "")))
        displays = display_list()
        saved = int(settings.value("monitor", displays[0][0] if displays else 0))
        self._display_id = saved if any(item[0] == saved for item in displays) else (
            displays[0][0] if displays else 0
        )
        self._manual_points = self._stored_points(settings)
        self.preview.set_points(self._manual_points)
        self._board_changed()
        self._fit(0)
        self._scan_wifi()

    def _save(self) -> None:
        settings = QSettings()
        settings.setValue("leds", self.leds.value())
        settings.setValue("board", self._board_id())
        settings.setValue("pin", self.pin.value())
        settings.setValue("ssid", self._ssid())
        settings.setValue("ota_password", self._ota_password)
        settings.setValue("wifi_password", self.wifi_password.text())
        settings.setValue("port", self.port.currentData() or "")
        settings.setValue("host", self.host.text().strip())
        settings.setValue("monitor", self._display_id)
        settings.setValue("order", COLOR_ORDER)
        settings.setValue("udp_port", UDP_PORT)

    def _board_id(self) -> str:
        for board_id, button in self.board_buttons.items():
            if button.isChecked():
                return board_id
        return "esp32"

    def _led_count(self) -> int:
        if getattr(self, "side_boxes", None):
            return max(1, sum(self._side_counts()))
        return max(1, int(self.leds.value()))

    def _pack(self, pixels: np.ndarray) -> bytes:
        """Плата принимает пакет только на число диодов из прошивки. Лишние остаются тёмными."""
        need = max(int(pixels.shape[0]), int(self._firmware_leds or 0))
        if need > pixels.shape[0]:
            extra = np.zeros((need - pixels.shape[0], 3), dtype=np.uint8)
            pixels = np.concatenate([pixels, extra], axis=0)
        return pack_colors(pixels)

    def _is_esp(self) -> bool:
        return self._board_id() == "esp32"

    def _board_changed(self) -> None:
        esp = self._is_esp()
        self.wifi_box.setVisible(esp)
        if not self._pin_touched:
            self.pin.blockSignals(True)
            self.pin.setValue(5 if esp else 6)
            self.pin.blockSignals(False)
        self._fit(self.stack.currentIndex())

    def _pin_edited(self) -> None:
        self._pin_touched = True

    def _fit(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        current = self.stack.currentWidget()
        if isinstance(current, QScrollArea) and current.widget() is not None:
            current.widget().updateGeometry()
            height = current.widget().sizeHint().height() + 36
        else:
            height = current.sizeHint().height() + 36
        screen = self.screen() or QApplication.primaryScreen()
        limit = screen.availableGeometry().height() - 48 if screen is not None else 900
        self.setFixedHeight(max(420, min(height, limit)))

    def _show_setup(self) -> None:
        if self.transmitting:
            self._stop()
        self._fit(0)

    def _show_control(self) -> None:
        self._save()
        name = "ESP32" if self._is_esp() else "Arduino Nano"
        self.control_title.setText(f"{name} · {self._led_count()} диодов")
        self.find_button.setVisible(self._is_esp())
        self.device_box.setVisible(self._is_esp())
        self._fit(1)
        if self._is_esp() and not self.host.text().strip():
            self._discover()

    def _fill_ports(self, prefer: str | None = None) -> None:
        current = prefer if prefer is not None else (self.port.currentData() or "")
        self.port.blockSignals(True)
        self.port.clear()
        ports = list_serial_ports()
        if not ports:
            self.port.addItem("Плата не видна", "")
        for device in ports:
            short = device.rsplit("/", 1)[-1]
            self.port.addItem(short, device)
        index = self.port.findData(current)
        if index < 0:
            usb = next((i for i in range(self.port.count()) if "usb" in str(self.port.itemData(i)).lower()), -1)
            index = usb if usb >= 0 else 0
        self.port.setCurrentIndex(max(0, index))
        self.port.blockSignals(False)

    def _sync_buttons(self) -> None:
        for mode, button in self.play_buttons.items():
            button.blockSignals(True)
            button.setChecked(mode == self.play and self.transmitting)
            button.blockSignals(False)
        show_colors = self.transmitting and self.play == "all"
        show_camera = self.transmitting and self.play in {"camera", "tv"}
        changed = False
        if self.color_box.isVisible() != show_colors:
            self.color_box.setVisible(show_colors)
            changed = True
        if self.camera_box.isVisible() != show_camera:
            self.camera_box.setVisible(show_camera)
            changed = True
        if changed and self.stack.currentIndex() == 1:
            self._fit(1)

    def _start(self, mode: str) -> None:
        self._off_until = 0.0
        self.play = mode
        self._chase_at = 0.0
        if self._is_esp() and not self.host.text().strip():
            self._pending_play = mode
            self.transmitting = False
            self._device_status = "Ищу ESP32 в Wi-Fi…"
            self._sync_buttons()
            self._render_status()
            self._snapshot()
            self._discover()
            return
        if not self._is_esp() and not (self.port.currentData() or ""):
            self.play = None
            self.transmitting = False
            self._device_status = "Подключи Arduino по USB."
            self._sync_buttons()
            self._render_status()
            return
        self._pending_play = None
        self.transmitting = True
        self._previous = None
        self._device_status = {
            "screen": "На ленту идёт цвет с экрана.",
            "camera": "Камера смотрит на телевизор. Сдвинь точки по углам.",
            "tv": "Подключаюсь к телевизору…",
            "chase": "Красный огонёк идёт по каждому диоду.",
            "all": f"Все диоды: {self._fill_name}.",
        }[mode]
        self._chase_at = 0.0
        self._sync_buttons()
        self._render_status()
        self._push_config()
        self._snapshot()
        self._use_camera(mode == "camera")
        self._use_tv(mode == "tv")
        if mode in {"chase", "all"}:
            self._push_pattern(force=True)

    def _stop(self) -> None:
        was = self.transmitting
        self.transmitting = False
        self.play = None
        self._pending_play = None
        self._snapshot()
        self._use_camera(False)
        self._use_tv(False)
        self._sync_buttons()
        if was:
            black = np.zeros((self._led_count(), 3), dtype=np.uint8)
            self.bar.set_pixels(black)
            self._off_packet = self._pack(black)
            self._off_until = time.monotonic() + 2.0
            self._off_next = 0.0
            self._device_status = "Выключаю ленту…"
        else:
            self._device_status = "Лента выключена."
        self._render_status()

    def _push_config(self) -> None:
        if not self.transmitting:
            return
        esp = self._is_esp()
        self.sender.configure(
            active=True,
            serial_on=not esp,
            port=self.port.currentData() or "",
            udp_on=esp,
            host=self.host.text().strip(),
            udp_port=UDP_PORT,
        )

    def _on_device_status(self, text: str) -> None:
        self._device_status = text
        self._render_status()

    def _render_status(self) -> None:
        if self.play in {"camera", "tv"} and self.transmitting and not self._device_status.startswith(
            ("Wi-Fi", "Прямой адрес")
        ):
            text = self._camera_status or self._device_status
        elif self.play in {"chase", "all"} and self.transmitting:
            text = self._device_status
        else:
            text = self.grab_error or self._device_status
        if self.stack.currentIndex() == 0:
            self.setup_status.setText(text)
        else:
            self.status.setText(text or "Выбери, что включить на ленте.")

    def _snapshot(self) -> None:
        count = self.leds.value() if self.play == "screen" and self._is_esp() else self._led_count()
        mode = self.play if self.transmitting else None
        self._shot = {
            "rows": 1,
            "cols": count,
            "mode": "strip",
            "reverse": True,
            "serpentine": False,
            "repeat": 1,
            "red": 1.0,
            "green": 1.0,
            "blue": 1.0,
            "brightness": 100,
            "smooth": 0.0,
            "chase": mode == "chase",
            "fill": self._fill_color if mode == "all" else None,
            "source": mode or "",
            "transmit": self.transmitting and mode == "screen",
            "send": self.transmitting and mode in {"screen", "chase", "all"},
        }

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loop_started:
            self._loop_started = True
            if not screen_access():
                self.grab_error = (
                    "Нет доступа к записи экрана. Системные настройки → "
                    "Конфиденциальность и безопасность → Запись экрана → включи Терминал или Cursor."
                )
                self._render_status()
            self._snapshot()
            self._pump = threading.Thread(target=self._pump_loop, name="ampilight-frames", daemon=True)
            self._pump.start()
            QTimer.singleShot(0, self.tick)

    def _pump_loop(self) -> None:
        display_id = self._display_id if isinstance(self._display_id, int) else 0
        try:
            self.stream.start(display_id, max_edge=1600, fps=60)
            self.grab_error = ""
        except Exception as exc:
            self.grab_error = f"Захват экрана: {exc}"
            return
        last_seq = 0
        while self._alive:
            pending = self._pending_display
            if pending is not None and pending != display_id:
                self._pending_display = None
                display_id = pending
                try:
                    self.stream.start(display_id, max_edge=1600, fps=60)
                    self.grab_error = ""
                    last_seq = 0
                except Exception as exc:
                    self.grab_error = f"Захват экрана: {exc}"
                continue
            got = self.stream.take(last_seq, 0.2)
            if not self._alive or got is None:
                continue
            seq, frame = got
            last_seq = seq
            try:
                self._consume(seq, frame)
            except Exception as exc:
                self.grab_error = f"Кадр: {exc}"

    def _consume(self, seq: int, frame: np.ndarray) -> None:
        shot = self._shot
        if shot.get("source") in {"camera", "tv", "chase", "all"}:
            return
        count = output_length("strip", shot["cols"], 1, 1)
        if shot.get("chase"):
            pixels = np.zeros((count, 3), dtype=np.uint8)
            now_chase = time.monotonic()
            if self._chase_at == 0.0:
                self._chase_index = 0
                self._chase_at = now_chase + 0.08
            elif now_chase >= self._chase_at:
                self._chase_at = now_chase + 0.08
                self._chase_index = (self._chase_index + 1) % count
            if self._chase_index >= count:
                self._chase_index = 0
            pixels[self._chase_index] = (255, 0, 0)
            self._previous = pixels
        elif shot.get("fill") is not None:
            pixels = np.empty((count, 3), dtype=np.uint8)
            pixels[:] = shot["fill"]
            self._previous = pixels
        else:
            self._chase_at = 0.0
            _grid, pixels = compose_pixels(
                frame,
                rows=shot["rows"],
                cols=shot["cols"],
                mode="strip",
                reverse=shot["reverse"],
                serpentine=False,
                repeat=1,
                red_gain=shot["red"],
                green_gain=shot["green"],
                blue_gain=shot["blue"],
                brightness=shot["brightness"],
                sampler=self._sampler,
            )
            pixels = blend(self._previous, pixels, shot["smooth"])
            self._previous = pixels
        now = time.monotonic()
        self._fps_marks.append(now)
        self._fps_marks = [mark for mark in self._fps_marks if mark >= now - 1.0]
        mean = float(frame[::24, ::24].mean()) if frame.size else 0.0
        with self._latest_lock:
            self._latest = {"seq": seq, "pixels": pixels, "mean": mean}
            self._pump_fps = len(self._fps_marks)
        if shot.get("send"):
            self.sender.submit(self._pack(pixels))

    def tick(self) -> None:
        if not self._alive:
            return
        self._snapshot()
        with self._latest_lock:
            latest = self._latest
        if latest is not None and latest["seq"] != self._shown_seq:
            self._shown_seq = latest["seq"]
            self.frames_seen = latest["seq"]
            self.last_mean = latest["mean"]
            self.bar.set_pixels(latest["pixels"])
        if (
            self.play == "screen"
            and self.frames_seen > 8
            and self.last_mean < 0.5
            and not self.grab_error
        ):
            self.grab_error = (
                "Экран считывается чёрным. Включи запись экрана для Terminal или Cursor."
            )
        elif self.frames_seen > 8 and self.last_mean >= 0.5 and self.grab_error.startswith("Экран считывается"):
            self.grab_error = ""
        self._hold_off()
        self._push_pattern()
        self._render_status()
        self._watch_camera()
        if self._alive:
            QTimer.singleShot(16, self.tick)

    def start_from_camera(self) -> None:
        self._show_control()
        self._start("camera")

    def start_desk_screen(self) -> None:
        """Прямая лента стола: 27 долей экрана на ESP32, без обхода через Hyperion."""
        self.board_buttons["esp32"].setChecked(True)
        self.leds.setValue(27)
        self.host.setText("192.168.100.9")
        self._show_control()
        self.control_title.setText("ESP32 · 27 диодов")
        self._start("screen")

    def _use_camera(self, on: bool) -> None:
        if not on:
            self.camera.stop()
            self._camera_status = ""
            self._camera_frames = 0
            self._camera_on_at = 0.0
            if self.preview.isVisible():
                self.preview.hide()
                self.frame_hint.hide()
                if self.stack.currentIndex() == 1:
                    self._fit(1)
            return
        self._camera_frames = 0
        self._camera_on_at = time.monotonic()
        self._preview_at = 0.0
        self._camera_seq = 0
        self.preview.set_points(self._manual_points)
        self.preview.show()
        self.frame_hint.show()
        self._fit(1)
        black = np.zeros((self._led_count(), 3), dtype=np.uint8)
        self.bar.set_pixels(black)
        self.sender.submit(self._pack(black))
        error = self.camera.start()
        if error:
            self._set_camera_status(error)
        else:
            self._set_camera_status("Включаю камеру ноутбука…")

    def _set_camera_status(self, text: str) -> None:
        if text == self._camera_status:
            return
        self._camera_status = text
        self._render_status()

    def _watch_camera(self) -> None:
        if self.play != "camera" or not self.transmitting or self._camera_frames:
            return
        if not self._camera_on_at or time.monotonic() - self._camera_on_at < 4:
            return
        if self._camera_status.startswith(("Нет доступа", "Камера:", "Камера ноутбука не")):
            return
        self._set_camera_status(
            "Камера молчит. Системные настройки → Конфиденциальность и безопасность → "
            "Камера → включи Cursor."
        )

    def _on_camera_failed(self, message: str) -> None:
        self._set_camera_status(message)

    def _stored_points(self, settings: QSettings) -> tuple[tuple[float, float], ...]:
        try:
            points = tuple(
                (
                    float(settings.value(f"quad_x{index}", -1)),
                    float(settings.value(f"quad_y{index}", -1)),
                )
                for index in range(4)
            )
        except (TypeError, ValueError):
            points = ()
        if len(points) == 4 and all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in points):
            return points
        try:
            x = float(settings.value("frame_x", -1))
            y = float(settings.value("frame_y", -1))
            width = float(settings.value("frame_w", -1))
            height = float(settings.value("frame_h", -1))
        except (TypeError, ValueError):
            x = y = width = height = -1
        if width >= 0.04 and height >= 0.04 and x >= 0 and y >= 0:
            return (
                (x, y),
                (min(1.0, x + width), y),
                (min(1.0, x + width), min(1.0, y + height)),
                (x, min(1.0, y + height)),
            )
        return ((0.18, 0.16), (0.82, 0.16), (0.82, 0.84), (0.18, 0.84))

    def _frame_drawn(self, points: tuple[tuple[float, float], ...]) -> None:
        self._manual_points = tuple((float(x), float(y)) for x, y in points)
        settings = QSettings()
        for index, (x, y) in enumerate(self._manual_points):
            settings.setValue(f"quad_x{index}", x)
            settings.setValue(f"quad_y{index}", y)

    def _on_camera_frame(self, frame: np.ndarray) -> None:
        if self.play != "camera" or not self.transmitting or not self._alive:
            return
        self._camera_frames += 1
        frame = grade_picture(
            frame,
            brightness=self.bright_slider.value() / 100.0,
            contrast=self.contrast_slider.value() / 100.0,
        )
        now = time.monotonic()
        if now - self._preview_at >= 0.1:
            self._preview_at = now
            view = frame
            if view.shape[1] > 420:
                factor = max(1, view.shape[1] // 420)
                view = view[::factor, ::factor]
            self.preview.set_image(view)
        host = self.host.text().strip()
        where = f"Плата {host}. " if host else ""
        points = self._manual_points
        if points is None:
            self._set_camera_status(f"{where}Сдвинь жёлтые точки на углы телевизора.")
            return
        left, top, right, bottom = self._side_counts()
        count = left + top + right + bottom
        self._set_camera_status(
            f"{where}Слева {left}, сверху {top}, справа {right}, снизу {bottom}. "
            f"Глубина {self.depth_slider.value()}%."
        )
        pixels = sample_perimeter(
            frame,
            points,
            count,
            self.depth_slider.value() / 100.0,
            mirror=self.camera_mirror.isChecked(),
            counts=(left, top, right, bottom),
        )
        if self.camera_reverse.isChecked():
            pixels = pixels[::-1].copy()
        pixels = blend(self._previous, pixels, 0.45)
        self._previous = pixels
        mean = float(frame[::8, ::8].mean()) if frame.size else 0.0
        self._camera_seq += 1
        with self._latest_lock:
            self._latest = {"seq": self._camera_seq, "pixels": pixels, "mean": mean}
        self.sender.submit(self._pack(pixels))

    def _use_tv(self, on: bool) -> None:
        if not on:
            if self.tv.running():
                self.tv.stop()
            if self.play != "camera" and self.preview.isVisible():
                self.preview.hide()
                if self.stack.currentIndex() == 1:
                    self._fit(1)
            return
        self._tv_marks = []
        self._preview_at = 0.0
        self._camera_seq = 0
        self.preview.set_points(None)
        self.preview.show()
        self.frame_hint.hide()
        self._fit(1)
        self._set_camera_status("Подключаюсь к телевизору по adb…")
        self._restart_tv()

    def _restart_tv(self) -> None:
        left, top, right, bottom = self._side_counts()
        size = grab_size(top, bottom, left, right)
        fps = self.tv_fps_slider.value()
        if self.tv.running() and (*size, fps) == (self.tv.width, self.tv.height, self.tv.fps):
            return
        self.tv.start(*size, fps)

    def _on_tv_frame(self, frame: np.ndarray) -> None:
        if self.play != "tv" or not self.transmitting or not self._alive:
            return
        now = time.monotonic()
        self._tv_marks.append(now)
        self._tv_marks = [mark for mark in self._tv_marks if mark >= now - 2.0]
        if now - self._preview_at >= 0.1:
            self._preview_at = now
            self.preview.set_image(frame)
        left, top, right, bottom = self._side_counts()
        pixels = sample_perimeter(
            frame,
            ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            left + top + right + bottom,
            self.depth_slider.value() / 100.0,
            counts=(left, top, right, bottom),
        )
        if self.camera_reverse.isChecked():
            pixels = pixels[::-1].copy()
        pixels = blend(self._previous, pixels, 0.3)
        self._previous = pixels
        host = self.host.text().strip()
        fps = len(self._tv_marks) / 2.0
        guarded = " Экран защищён (Netflix, Кинопоиск) — телевизор отдаёт чёрный." if not frame.any() else ""
        self._set_camera_status(
            f"Телевизор {self.tv.serial}: снимок {self.tv.width}×{self.tv.height}, {fps:.0f} кадр/с. "
            + (f"Плата {host}." if host else "Плата не выбрана.")
            + guarded
        )
        self._camera_seq += 1
        with self._latest_lock:
            self._latest = {"seq": self._camera_seq, "pixels": pixels, "mean": float(frame.mean())}
        self.sender.submit(self._pack(pixels))

    def _pick_color(self, rgb: tuple[int, int, int], name: str) -> None:
        self._fill_color = rgb
        self._fill_name = name
        self.color_name.setText(f"Сейчас {name}")
        for swatch, color, _label in self._swatches:
            swatch.setStyleSheet(_swatch_style(color, color == rgb))
        if self.play == "all" and self.transmitting:
            self._device_status = f"Все диоды: {name}."
            self._render_status()
            self._snapshot()
            self._push_pattern(force=True)

    def _lamp_color(self) -> tuple[int, int, int]:
        """Полный белый на всех диодах сажает питание, и плата перестаёт слышать команды."""
        red, green, blue = self._fill_color
        peak = max(red, green, blue, 1)
        scale = min(1.0, 90 / peak)
        return (
            int(round(red * scale)),
            int(round(green * scale)),
            int(round(blue * scale)),
        )

    def _hold_off(self) -> None:
        if not self._off_until or self.transmitting:
            return
        now = time.monotonic()
        if now >= self._off_until:
            self._off_until = 0.0
            if self._off_packet:
                self.sender.stop_output(self._off_packet)
            self._device_status = "Лента выключена."
            self._render_status()
            return
        if now >= self._off_next and self._off_packet:
            self._off_next = now + 0.05
            self.sender.submit(self._off_packet)

    def _push_pattern(self, force: bool = False) -> None:
        if not self.transmitting or self.play not in {"chase", "all"}:
            return
        now = time.monotonic()
        if not force and now < self._chase_at:
            return
        count = self._led_count()
        if self.play == "all":
            pixels = np.empty((count, 3), dtype=np.uint8)
            pixels[:] = self._lamp_color()
            self._chase_at = now + 0.2
        else:
            pixels = np.zeros((count, 3), dtype=np.uint8)
            pixels[self._chase_index % count] = (255, 0, 0)
            self._chase_index = (self._chase_index + 1) % count
            self._chase_at = now + 0.08
        self._previous = pixels
        self._pattern_seq += 1
        with self._latest_lock:
            self._latest = {"seq": self._pattern_seq, "pixels": pixels, "mean": 10.0}
        self.sender.submit(self._pack(pixels))

    def _device_picked(self) -> None:
        self.host.setText(str(self.devices.currentData() or ""))
        if self.transmitting and self._is_esp():
            self._push_config()

    def _discover(self) -> None:
        if self._finder is not None and self._finder.isRunning():
            return
        self.find_button.setEnabled(False)
        if not self._device_status:
            self._device_status = "Ищу ESP32 в Wi-Fi…"
        self._render_status()
        self._finder = FindThread(UDP_PORT)
        self._finder.found.connect(self._on_found)
        self._finder.start()

    def _on_found(self, result) -> None:
        self.find_button.setEnabled(True)
        pending = self._pending_play
        if isinstance(result, Exception):
            self._pending_flash = False
            self._device_status = f"Поиск: {result}"
            self._render_status()
            return
        if not result:
            self._pending_flash = False
            self.devices.blockSignals(True)
            self.devices.clear()
            self.devices.addItem("Плата не найдена", "")
            self.devices.blockSignals(False)
            self.host.setText("")
            self._device_status = "ESP32 не ответила. Она должна быть в этой Wi-Fi и уже прошита."
            self._pending_play = None
            self.play = None
            self._sync_buttons()
            self._render_status()
            return
        saved = self.host.text().strip()
        self.devices.blockSignals(True)
        self.devices.clear()
        for ip, leds in result:
            label = f"{ip} · {leds} диодов" if leds else ip
            self.devices.addItem(label, ip)
        index = self.devices.findData(saved)
        self.devices.setCurrentIndex(index if index >= 0 else 0)
        self.devices.blockSignals(False)
        self._device_picked()
        ip = str(self.devices.currentData() or "")
        leds = next((count for addr, count in result if addr == ip), 0)
        if leds:
            self._firmware_leds = int(leds)
            QSettings().setValue("firmware_leds", self._firmware_leds)
        note = f"Плата в сети: {ip}"
        if len(result) > 1:
            note += f". Найдено {len(result)}, выбери нужную"
        if leds and leds != self._led_count():
            note += f". В прошивке {leds} диодов, в окне {self._led_count()}"
        self._device_status = note
        self._render_status()
        if self._pending_flash:
            self._pending_flash = False
            self._flash_clicked()
            return
        if pending:
            self._start(pending)

    def _flash_clicked(self) -> None:
        if self._flash is not None and self._flash.isRunning():
            return
        board_id = self._board_id()
        port = self.port.currentData() or ""
        ssid = current_ssid(allow_slow=False) or self._ssid()
        if board_id == "esp32" and ssid and self.ssid.findText(ssid) < 0:
            self.ssid.blockSignals(True)
            self.ssid.clear()
            self.ssid.addItem(ssid)
            self.ssid.blockSignals(False)
        if board_id == "esp32" and not ssid:
            self._device_status = "Этот компьютер не в Wi-Fi. Подключи его к сети и нажми Обновить."
            self._render_status()
            return
        if board_id == "esp32" and not self.wifi_password.text():
            self._device_status = "Напиши пароль Wi-Fi. Без него плата не найдётся после отключения USB."
            self._render_status()
            return
        if not port:
            self._fill_ports()
            port = self.port.currentData() or ""
        if board_id == "esp32" and not port:
            if not self.host.text().strip():
                self._pending_flash = True
                self._device_status = "Ищу плату в Wi-Fi, чтобы прошить без USB…"
                self._render_status()
                self._discover()
                return
            port = self.host.text().strip()
        if not port:
            self._device_status = "Мак не видит плату по USB. Проверь кабель и общую землю."
            self._render_status()
            return
        if self.transmitting:
            self._stop()
        self.sender.release_port()
        self.log.clear()
        self.flash_button.setEnabled(False)
        over_wifi = "." in port and "/" not in port
        self._device_status = "Прошиваю по Wi-Fi…" if over_wifi else "Прошиваю по USB…"
        self._render_status()
        self._flash = FlashJob(
            board_id=board_id,
            port=port,
            leds=self.leds.value(),
            pin=self.pin.value(),
            order=COLOR_ORDER,
            ssid=ssid if board_id == "esp32" else "",
            password=self.wifi_password.text(),
            udp_port=UDP_PORT,
            ota_auth=self._ota_password or self.wifi_password.text(),
        )
        self._flash.line.connect(self.log.appendPlainText)
        self._flash.done.connect(self._flash_done)
        self._flash.start()

    def _flash_done(self, ok: bool, message: str) -> None:
        self.flash_button.setEnabled(True)
        self.log.appendPlainText(message)
        if ok:
            if self._is_esp():
                self._ota_password = self.wifi_password.text()
                self._save()
            self._device_status = "Прошивка записана. Дальше плату можно оставить без USB."
            self._show_control()
        else:
            self._device_status = message
            self._render_status()

    def closeEvent(self, event) -> None:
        self._alive = False
        if self.transmitting:
            self.transmitting = False
            black = np.zeros((self._led_count(), 3), dtype=np.uint8)
            self.sender.stop_output(self._pack(black))
            time.sleep(0.12)
        self._save()
        self.camera.stop()
        self.tv.stop()
        self.stream.stop()
        if self._pump is not None:
            self._pump.join(timeout=1.5)
        self.sender.stop()
        super().closeEvent(event)
