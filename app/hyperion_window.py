"""Окно Hyperion: сначала подключение, затем цвет ленты."""

from __future__ import annotations

import math
import queue
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect, QRectF, QSettings, QSize, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSystemTrayIcon,
    QScrollArea,
    QApplication,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.discover import network_is_up
from app.glass import SHADOW, GlassWindow, glow_gradient
from app.hyperion import (
    DEFAULT_HOST,
    DEFAULT_INSTANCE,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_PRIORITY,
    DESK_NAME,
    LEGACY_SCREEN,
    SCREEN_MODE,
    SCREEN_NAMES,
    TV_ADAPTIVE,
    HyperionClient,
)
from app.sck import ScreenStream, encode_strip, fit_leds, main_display, open_screen_settings, request_screen_access
from app.search_page import SearchPage

SOLID = "Solid"

PRESETS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("Красный", (255, 59, 48)),
    ("Оранжевый", (255, 149, 0)),
    ("Жёлтый", (255, 204, 0)),
    ("Зелёный", (48, 209, 88)),
    ("Голубой", (50, 173, 230)),
    ("Синий", (10, 132, 255)),
    ("Фиолетовый", (175, 82, 222)),
    ("Белый", (255, 255, 255)),
)


def _luma(rgb: tuple[int, int, int]) -> float:
    red, green, blue = rgb
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


class _BrightBar(QWidget):
    """Толстая полоса яркости: заливка растёт слева направо."""

    changed = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = 100
        self._color = (255, 168, 72)
        self._drag = False

    def set_value(self, value: int) -> None:
        self._value = max(1, min(100, int(value)))
        self.update()

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        self._color = rgb
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(bounds, 16, 16)
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(245, 245, 247, 240))
        painter.drawRect(bounds)
        fill = QColor(*self._color)
        fill.setAlpha(230)
        painter.setBrush(fill)
        painter.drawRect(QRectF(0, 0, self.width() * self._value / 100, self.height()))
        painter.setClipping(False)
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        ink = QColor(255, 255, 255) if _luma(self._color) < 150 else QColor(13, 30, 53)
        painter.setPen(ink)
        painter.drawText(bounds.adjusted(14, 0, -14, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "Яркость")
        number = QColor(13, 30, 53) if self._value < 88 else ink
        painter.setPen(number)
        painter.drawText(bounds.adjusted(14, 0, -14, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), str(self._value))
        painter.end()

    def _at(self, x: float) -> int:
        return max(1, min(100, round(x / max(1, self.width()) * 100)))

    def mousePressEvent(self, event) -> None:
        self._drag = True
        self._set(self._at(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            self._set(self._at(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = False
        super().mouseReleaseEvent(event)

    def _set(self, value: int) -> None:
        if value == self._value:
            return
        self._value = value
        self.update()
        self.changed.emit(value)


class _ColorWheel(QWidget):
    """Круглая палитра: угол — оттенок, радиус — насыщенность."""

    chosen = pyqtSignal(int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(176, 176)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue = 28.0
        self._sat = 0.72
        self._drag = False

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        hue, sat, _value, _alpha = QColor(*rgb).getHsv()
        if hue >= 0:
            self._hue = float(hue)
        self._sat = 0.0 if sat < 0 else sat / 255
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self.width() / 2 - 2
        disc = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        hue = QConicalGradient(center, 0)
        for step in range(13):
            hue.setColorAt(step / 12, QColor.fromHsv((step * 30) % 360, 255, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hue))
        painter.drawEllipse(disc)
        fade = QRadialGradient(center, radius)
        fade.setColorAt(0, QColor(255, 255, 255))
        fade.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(fade))
        painter.drawEllipse(disc)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.5))
        painter.drawEllipse(disc.adjusted(0.5, 0.5, -0.5, -0.5))
        knob = self._knob_center(radius)
        color = QColor.fromHsv(int(self._hue) % 360, int(self._sat * 255), 255)
        painter.setPen(QPen(QColor(255, 255, 255), 2.5))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(knob.x() - 8, knob.y() - 8, 16, 16))
        painter.end()

    def _knob_center(self, radius: float) -> QPointF:
        reach = self._sat * (radius - 10)
        angle = math.radians(self._hue)
        return QPointF(
            self.width() / 2 + math.cos(angle) * reach,
            self.height() / 2 - math.sin(angle) * reach,
        )

    def mousePressEvent(self, event) -> None:
        self._drag = True
        self._pick(event.position())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            self._pick(event.position())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = False
        super().mouseReleaseEvent(event)

    def _pick(self, point: QPointF) -> None:
        dx = point.x() - self.width() / 2
        dy = point.y() - self.height() / 2
        radius = self.width() / 2 - 2
        self._hue = (math.degrees(math.atan2(-dy, dx)) + 360) % 360
        self._sat = min(1.0, math.hypot(dx, dy) / max(1.0, radius - 10))
        self.update()
        color = QColor.fromHsv(int(self._hue) % 360, int(round(self._sat * 255)), 255)
        self.chosen.emit(color.red(), color.green(), color.blue())


class _Swatches(QWidget):
    """Ряд готовых цветов."""

    chosen = pyqtSignal(int, int, int)

    def __init__(self, presets: tuple[tuple[str, tuple[int, int, int]], ...]) -> None:
        super().__init__()
        self._presets = presets
        self._current: tuple[int, int, int] | None = None
        self._spots: list[QRectF] = []
        self.setFixedHeight(36)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_current(self, rgb: tuple[int, int, int]) -> None:
        self._current = rgb
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        count = len(self._presets)
        gap = 8.0
        size = min(26.0, (self.width() - gap * (count - 1)) / max(1, count))
        total = count * size + (count - 1) * gap
        x = (self.width() - total) / 2
        y = (self.height() - size) / 2
        self._spots = []
        for _name, rgb in self._presets:
            rect = QRectF(x, y, size, size)
            self._spots.append(rect)
            painter.setPen(QPen(QColor(255, 255, 255, 170), 1))
            painter.setBrush(QColor(*rgb))
            painter.drawEllipse(rect)
            if rgb == self._current:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))
            x += size + gap
        painter.end()

    def _hit(self, point: QPointF) -> int:
        for index, rect in enumerate(self._spots):
            if rect.adjusted(-4, -4, 4, 4).contains(point):
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:
        index = self._hit(event.position())
        self.setToolTip(self._presets[index][0] if index >= 0 else "")

    def mousePressEvent(self, event) -> None:
        index = self._hit(event.position())
        if index >= 0:
            red, green, blue = self._presets[index][1]
            self.chosen.emit(red, green, blue)
        event.accept()


class StripBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(36)
        self._color = QColor("#ffa848")

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        self._color = QColor(*rgb)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(self.rect().adjusted(0, 6, -1, -7))
        path = QPainterPath()
        path.addRoundedRect(bounds, 12, 12)
        painter.setClipPath(path)
        painter.fillPath(path, self._color)
        painter.end()


def _link_caption(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "лента"
    elif count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        word = "ленты"
    else:
        word = "лент"
    return f"На связи · {count} {word}"


class HyperionThread(QThread):
    linked = pyqtSignal(bool, str)
    note = pyqtSignal(str)
    failed = pyqtSignal(str)
    strips = pyqtSignal(object)
    modes = pyqtSignal(object)
    live = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._client = HyperionClient()

    @property
    def client(self) -> HyperionClient:
        return self._client

    def submit(self, job: tuple) -> None:
        self._queue.put(job)

    def request_stop(self) -> None:
        self._queue.put(("shutdown",))

    def run(self) -> None:
        while True:
            job = self._queue.get()
            if job[0] == "shutdown":
                try:
                    if self._client.connected:
                        self._client.clear()
                except (OSError, RuntimeError, ValueError, TypeError):
                    pass
                break
            self._handle(job)
        self._client.close()

    def _handle(self, job: tuple) -> None:
        kind = job[0]
        try:
            if kind == "connect":
                host, port, password = job[1], job[2], job[3]
                strips = self._client.connect(host, port, password)
                self._client.ensure_screen_effect()
                self.strips.emit(strips)
                self.modes.emit(list(self._client.modes))
                caption = _link_caption(len(strips))
                self.linked.emit(True, caption)
                self.note.emit(caption)
            elif kind == "peek":
                try:
                    self.live.emit(self._client.inspect(int(job[1])))
                except (OSError, RuntimeError, ValueError, TypeError):
                    return
            elif kind == "blank":
                self._client.blank(int(job[1]))
            elif kind == "wake":
                self._client.wake(int(job[1]))
            elif kind == "capture":
                enabled, instance = bool(job[1]), int(job[2])
                self._client.set_capture(instance, enabled)
            elif kind == "effect":
                name, instance = job[1], job[2]
                self._client.set_effect(name, DEFAULT_PRIORITY, instance)
                self.note.emit(f"Режим {name}")
            elif kind == "color":
                rgb, priority, instance = job[1], job[2], job[3]
                try:
                    self._client.clear(int(priority), int(instance), forget=False)
                except (OSError, RuntimeError, ValueError, TypeError):
                    pass
                self._client._force_show = True
                self._client.set_color(rgb, priority, instance)
                red, green, blue = rgb
                self.note.emit(f"На ленте {red}, {green}, {blue}")
            elif kind == "image":
                raw, width, height, instance = job[1], job[2], job[3], job[4]
                if height == 1:
                    try:
                        boxes = self._client.led_boxes(int(instance))
                    except (OSError, RuntimeError, ValueError, TypeError):
                        boxes = []
                    raw, width, height = encode_strip(raw, boxes)
                self._client.set_image(raw, width, height, DEFAULT_PRIORITY, instance, None)
            elif kind == "clear":
                instance = job[1] if len(job) > 1 else None
                forget = job[2] if len(job) > 2 else True
                self._client.clear(instance=instance, forget=bool(forget))
                self.note.emit("Лента погашена")
            elif kind == "disconnect":
                try:
                    self._client.clear()
                except (OSError, RuntimeError, ValueError):
                    pass
                self._client.close()
                self.linked.emit(False, "Отключено")
                self.note.emit("Отключено")
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            message = str(exc) or "Ошибка Hyperion"
            self.failed.emit(message)
            self.note.emit(message)
            if kind in {"connect", "color", "clear"} and not self._client.connected:
                self.linked.emit(False, message)


def _bootstrap(*bodies: str) -> str:
    paths = "".join(f'<path d="{body}"/>' for body in bodies)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="#0d1e35" '
        f'viewBox="0 0 16 16">{paths}</svg>'
    )


_BOOTSTRAP = {
    "globe": _bootstrap(
        "M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8m7.5-6.923c-.67.204-1.335.82-1.887 1.855A8 8 0 0 0 5.145 4H7.5z"
        "M4.09 4a9.3 9.3 0 0 1 .64-1.539 7 7 0 0 1 .597-.933A7.03 7.03 0 0 0 2.255 4zm-.582 3.5c.03-.877.138-1.718.312-2.5H1.674a7 7 0 0 0-.656 2.5z"
        "M4.847 5a12.5 12.5 0 0 0-.338 2.5H7.5V5zM8.5 5v2.5h2.99a12.5 12.5 0 0 0-.337-2.5zM4.51 8.5a12.5 12.5 0 0 0 .337 2.5H7.5V8.5zm3.99 0V11h2.653c.187-.765.306-1.608.338-2.5z"
        "M5.145 12q.208.58.468 1.068c.552 1.035 1.218 1.65 1.887 1.855V12zm.182 2.472a7 7 0 0 1-.597-.933A9.3 9.3 0 0 1 4.09 12H2.255a7 7 0 0 0 3.072 2.472"
        "M3.82 11a13.7 13.7 0 0 1-.312-2.5h-2.49c.062.89.291 1.733.656 2.5zm6.853 3.472A7 7 0 0 0 13.745 12H11.91a9.3 9.3 0 0 1-.64 1.539 7 7 0 0 1-.597.933"
        "M8.5 12v2.923c.67-.204 1.335-.82 1.887-1.855q.26-.487.468-1.068zm3.68-1h2.146c.365-.767.594-1.61.656-2.5h-2.49a13.7 13.7 0 0 1-.312 2.5"
        "m2.802-3.5a7 7 0 0 0-.656-2.5H12.18c.174.782.282 1.623.312 2.5zM11.27 2.461c.247.464.462.98.64 1.539h1.835a7 7 0 0 0-3.072-2.472c.218.284.418.598.597.933"
        "M10.855 4a8 8 0 0 0-.468-1.068C9.835 1.897 9.17 1.282 8.5 1.077V4z",
    ),
    "ethernet": _bootstrap(
        "M14 13.5v-7a.5.5 0 0 0-.5-.5H12V4.5a.5.5 0 0 0-.5-.5h-1v-.5A.5.5 0 0 0 10 3H6a.5.5 0 0 0-.5.5V4h-1a.5.5 0 0 0-.5.5V6H2.5a.5.5 0 0 0-.5.5v7a.5.5 0 0 0 .5.5h11a.5.5 0 0 0 .5-.5"
        "M3.75 11h.5a.25.25 0 0 1 .25.25v1.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25v-1.5a.25.25 0 0 1 .25-.25"
        "m2 0h.5a.25.25 0 0 1 .25.25v1.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25v-1.5a.25.25 0 0 1 .25-.25"
        "m1.75.25a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v1.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25z"
        "M9.75 11h.5a.25.25 0 0 1 .25.25v1.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25v-1.5a.25.25 0 0 1 .25-.25"
        "m1.75.25a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v1.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25z",
        "M2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2zM1 2a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1z",
    ),
    "lock": _bootstrap(
        "M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2m3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2M5 8h6a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1",
    ),
    "eye": _bootstrap(
        "M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8M1.173 8a13 13 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5s3.879 1.168 5.168 2.457A13 13 0 0 1 14.828 8q-.086.13-.195.288c-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5s-3.879-1.168-5.168-2.457A13 13 0 0 1 1.172 8z"
        "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5M4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0",
    ),
    "lightbulb": _bootstrap(
        "M2 6a6 6 0 1 1 10.174 4.31c-.203.196-.359.4-.453.619l-.762 1.769A.5.5 0 0 1 10.5 13a.5.5 0 0 1 0 1 .5.5 0 0 1 0 1l-.224.447a1 1 0 0 1-.894.553H6.618a1 1 0 0 1-.894-.553L5.5 15a.5.5 0 0 1 0-1 .5.5 0 0 1 0-1 .5.5 0 0 1-.46-.302l-.761-1.77a2 2 0 0 0-.453-.618A5.98 5.98 0 0 1 2 6m6-5a5 5 0 0 0-3.479 8.592c.263.254.514.564.676.941L5.83 12h4.342l.632-1.467c.162-.377.413-.687.676-.941A5 5 0 0 0 8 1",
    ),
    "lightbulb-fill": _bootstrap(
        "M2 6a6 6 0 1 1 10.174 4.31c-.203.196-.359.4-.453.619l-.762 1.769A.5.5 0 0 1 10.5 13h-5a.5.5 0 0 1-.46-.302l-.761-1.77a2 2 0 0 0-.453-.618A5.98 5.98 0 0 1 2 6m3 8.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1l-.224.447a1 1 0 0 1-.894.553H6.618a1 1 0 0 1-.894-.553L5.5 15a.5.5 0 0 1-.5-.5",
    ),
    "eye-slash": _bootstrap(
        "M13.359 11.238C15.06 9.72 16 8 16 8s-3-5.5-8-5.5a7 7 0 0 0-2.79.588l.77.771A6 6 0 0 1 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13 13 0 0 1 14.828 8q-.086.13-.195.288c-.335.48-.83 1.12-1.465 1.755q-.247.248-.517.486z"
        "M11.297 9.176a3.5 3.5 0 0 0-4.474-4.474l.823.823a2.5 2.5 0 0 1 2.829 2.829zm-2.943 1.299.822.822a3.5 3.5 0 0 1-4.474-4.474l.823.823a2.5 2.5 0 0 0 2.829 2.829"
        "M3.35 5.47q-.27.24-.518.487A13 13 0 0 0 1.172 8l.195.288c.335.48.83 1.12 1.465 1.755C4.121 11.332 5.881 12.5 8 12.5c.716 0 1.39-.133 2.02-.36l.77.772A7 7 0 0 1 8 13.5C3 13.5 0 8 0 8s.939-1.721 2.641-3.238l.708.709zm10.296 8.884-12-12 .708-.708 12 12z",
    ),
}

_ICON_RENDERERS: dict[str, QSvgRenderer] = {}


def _paint_icon(painter: QPainter, kind: str, box: QRectF, fill: str = "#0d1e35") -> None:
    key = f"{kind}|{fill}"
    renderer = _ICON_RENDERERS.get(key)
    if renderer is None:
        svg = _BOOTSTRAP[kind].replace("#0d1e35", fill)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        _ICON_RENDERERS[key] = renderer
    renderer.render(painter, box)


class _Glyph(QWidget):
    """Значок Bootstrap внутри поля."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind
        self.setFixedSize(16, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_icon(painter, self._kind, QRectF(0, 0, 16, 16))
        painter.end()


class _EyeButton(QPushButton):
    """Глаз Bootstrap внутри поля пароля."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("eye")
        self.setCheckable(True)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Показать пароль")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_icon(painter, "eye-slash" if self.isChecked() else "eye", QRectF(6, 6, 16, 16))
        painter.end()


class _DevicePicker(QPushButton):
    """Поле выбора прибора со стрелкой справа."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("device")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)

    def set_name(self, name: str) -> None:
        self.setText(name)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(13, 30, 53), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        x = self.width() - 22
        y = self.height() / 2 - 2
        painter.drawLine(QPointF(x, y), QPointF(x + 4.5, y + 5))
        painter.drawLine(QPointF(x + 9, y), QPointF(x + 4.5, y + 5))
        painter.end()


_MENU_STYLE = """
QListWidget#deviceList {
    background: transparent;
    border: none;
    outline: none;
    color: #0d1e35;
    font-size: 15px;
    font-weight: 600;
    padding: 4px;
}
QListWidget#deviceList::item {
    background: transparent;
    color: #0d1e35;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
}
QListWidget#deviceList::item:hover { background: rgba(13, 30, 53, 0.06); }
QListWidget#deviceList::item:selected { background: #e7eeff; color: #0d1e35; }
"""


class _DeviceMenu(QFrame):
    """Светлый список под полем, с тонкой полосой прокрутки."""

    chosen = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("deviceMenu")
        self._list = QListWidget()
        self._list.setObjectName("deviceList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(1)
        self._list.setStyleSheet(_MENU_STYLE)
        self._list.viewport().setAutoFillBackground(False)
        self._list.itemClicked.connect(self._pick)
        bar = self._list.verticalScrollBar()
        bar.valueChanged.connect(lambda _value: self.update())
        bar.rangeChanged.connect(lambda _lo, _hi: self.update())
        self._drag = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 14, 6)
        outer.addWidget(self._list)

    def _thumb(self) -> QRectF | None:
        bar = self._list.verticalScrollBar()
        if bar.maximum() <= 0:
            return None
        track_top = 14.0
        track_h = max(1.0, self.height() - 28.0)
        span = bar.maximum() - bar.minimum() + max(1, bar.pageStep())
        thumb_h = min(track_h, max(32.0, track_h * bar.pageStep() / span))
        travel = track_h - thumb_h
        frac = (bar.value() - bar.minimum()) / max(1, bar.maximum() - bar.minimum())
        return QRectF(self.width() - 10, track_top + travel * frac, 4, thumb_h)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(13, 30, 53, 22), 1))
        painter.setBrush(QColor(245, 245, 247))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 16, 16)
        thumb = self._thumb()
        if thumb is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(13, 30, 53, 90))
            painter.drawRoundedRect(thumb, 2, 2)
        painter.end()

    def mousePressEvent(self, event) -> None:
        thumb = self._thumb()
        if thumb is not None and thumb.adjusted(-4, 0, 4, 0).contains(event.position()):
            self._drag = True
            self._grab = event.position().y() - thumb.top()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._drag:
            super().mouseMoveEvent(event)
            return
        bar = self._list.verticalScrollBar()
        thumb = self._thumb()
        if thumb is None:
            return
        track_h = max(1.0, self.height() - 28.0)
        travel = max(1.0, track_h - thumb.height())
        frac = (event.position().y() - self._grab - 14.0) / travel
        frac = min(1.0, max(0.0, frac))
        bar.setValue(round(bar.minimum() + frac * (bar.maximum() - bar.minimum())))

    def mouseReleaseEvent(self, event) -> None:
        self._drag = False
        super().mouseReleaseEvent(event)

    def present(self, anchor: QWidget, items: list[str], current: str) -> None:
        self._list.clear()
        selected = 0
        for index, name in enumerate(items):
            item = QListWidgetItem(name)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 36)))
            self._list.addItem(item)
            if name == current:
                selected = index
        if self._list.count():
            self._list.setCurrentRow(selected)
        self.setFont(anchor.font())
        self._list.setFont(anchor.font())
        self.setFixedWidth(max(anchor.width(), 180))
        height = min(280, 12 + self._list.count() * 38)
        self.setFixedHeight(max(56, height))
        self._list.scrollToItem(self._list.currentItem(), QListWidget.ScrollHint.PositionAtCenter)
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 8)))
        self.show()

    def _pick(self, item: QListWidgetItem) -> None:
        text = item.text()
        QTimer.singleShot(0, self.close)
        self.chosen.emit(text)


class _RangeBar(QWidget):
    """Один диапазон: левый ползунок — начало ленты, правый — конец."""

    changed = pyqtSignal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(46)
        self.setMinimumWidth(160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start = 0
        self._end = 100
        self._drag: str | None = None

    def values(self) -> tuple[int, int]:
        return self._start, self._end

    def set_values(self, start: int, end: int) -> None:
        self._start = max(0, min(96, int(start)))
        self._end = max(self._start + 4, min(100, int(end)))
        self.update()

    def _x(self, value: int) -> float:
        pad = 16.0
        span = max(1.0, self.width() - pad * 2)
        return pad + span * value / 100

    def _value(self, x: float) -> int:
        pad = 16.0
        span = max(1.0, self.width() - pad * 2)
        return max(0, min(100, round((x - pad) / span * 100)))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(245, 245, 247, 240))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 16, 16)
        track = QRectF(16, 19, max(1, self.width() - 32), 8)
        painter.setBrush(QColor(13, 30, 53, 36))
        painter.drawRoundedRect(track, 4, 4)
        left = self._x(self._start)
        right = self._x(self._end)
        painter.setBrush(QColor(77, 136, 255))
        painter.drawRoundedRect(QRectF(left, 19, max(8, right - left), 8), 4, 4)
        for center in (left, right):
            painter.setBrush(QColor(13, 30, 53))
            painter.drawEllipse(QRectF(center - 9, 13, 18, 18))
        painter.end()

    def _pick(self, x: float) -> str:
        if abs(x - self._x(self._start)) <= abs(x - self._x(self._end)):
            return "start"
        return "end"

    def mousePressEvent(self, event) -> None:
        self._drag = self._pick(event.position().x())
        self._move(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            self._move(event.position().x())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        super().mouseReleaseEvent(event)

    def _move(self, x: float) -> None:
        value = self._value(x)
        if self._drag == "start":
            value = min(value, self._end - 4)
            if value == self._start:
                return
            self._start = value
        else:
            value = max(value, self._start + 4)
            if value == self._end:
                return
            self._end = value
        self.update()
        self.changed.emit(self._start, self._end)


class StripFit:
    """Сколько диодов по сторонам и какой кусок экрана класть на стол."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.top = 0
        self.bottom = 27
        self.left = 0
        self.right = 0
        self.percent = 15
        self.span_start = 0
        self.span_end = 100
        self.capture_start = 85
        self.capture_end = 100
        self.mark = False

    def update(self, **values: int | bool) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self) -> tuple[int, int, int, int, int, int, int, bool, int, int]:
        with self._lock:
            return (
                self.top,
                self.bottom,
                self.left,
                self.right,
                self.percent,
                self.span_start,
                self.span_end,
                self.mark,
                self.capture_start,
                self.capture_end,
            )

    @property
    def total(self) -> int:
        with self._lock:
            count = self.top + self.bottom + self.left + self.right
        return count if count > 0 else 27


class _ScreenPump(QThread):
    """Кадры экрана на стол, пока выбран «адаптив». Гаснет, когда Home Assistant его снимает."""

    failed = pyqtSignal(str)

    def __init__(self, client: HyperionClient, instance: int, fit: StripFit) -> None:
        super().__init__()
        self._client = client
        self._instance = instance
        self._fit = fit
        self._gate = threading.Event()
        self._stream: ScreenStream | None = None

    def request_stop(self) -> None:
        self._gate.set()
        stream = self._stream
        if stream is not None:
            stream.wake()

    def run(self) -> None:
        stream = ScreenStream()
        self._stream = stream
        try:
            stream.start(main_display(), max_edge=1200, fps=10, embedded=True)
        except (OSError, RuntimeError, ValueError) as exc:
            self.failed.emit(str(exc) or "захват экрана не запустился")
            return
        misses = 0
        last = 0
        next_send = 0.0
        sent = False
        grace = 0.0
        next_hold = 0.0
        try:
            try:
                self._client.mute_blackborder(self._instance)
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
            while not self._gate.is_set():
                got = stream.take(last, 0.4)
                if self._gate.is_set():
                    break
                if got is None:
                    continue
                seq, frame = got
                last = seq
                now = time.monotonic()
                if now < next_send:
                    continue
                next_send = now + 0.12
                if sent and now >= next_hold:
                    next_hold = now + 0.6
                    try:
                        hold = self._client.screen_status(self._instance)
                    except (OSError, RuntimeError, ValueError, TypeError):
                        hold = "ours"
                    if hold == "cover":
                        try:
                            self._client.clear(DEFAULT_PRIORITY, self._instance, forget=True)
                        except (OSError, RuntimeError, ValueError, TypeError):
                            pass
                        break
                    if hold == "other" or (hold == "gone" and now >= grace):
                        break
                top, bottom, left, right, percent, span_start, span_end, mark, capture_start, capture_end = (
                    self._fit.snapshot()
                )
                row = fit_leds(
                    frame,
                    bottom,
                    left,
                    top,
                    right,
                    percent,
                    span_start,
                    span_end,
                    capture_start,
                    capture_end,
                )
                count = len(row) // 3
                if mark and count > 0:
                    row = bytes([255, 255, 255]) + bytes((count - 1) * 3)
                try:
                    boxes = self._client.led_boxes(self._instance)
                except (OSError, RuntimeError, ValueError, TypeError):
                    boxes = []
                raw, width, height = encode_strip(row, boxes)
                try:
                    self._client.set_image(
                        raw, width, height, DEFAULT_PRIORITY, self._instance, self._gate
                    )
                    sent = True
                    if grace <= 0:
                        grace = now + 1.5
                    misses = 0
                except (OSError, RuntimeError, ValueError, TypeError) as exc:
                    misses += 1
                    if misses < 3:
                        time.sleep(0.3)
                        continue
                    self.failed.emit(str(exc) or "Hyperion не принял экран")
                    break
        finally:
            stream.stop()
            self._stream = None


class _LampButton(QPushButton):
    """Лампа: контур выключен, тёплое свечение включено."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("lamp")
        self.setFixedSize(46, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lit = False
        self.setToolTip("Включить")

    def set_lit(self, lit: bool) -> None:
        self._lit = lit
        self.setToolTip("Выключить" if lit else "Включить")
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(245, 245, 247, 240))
        painter.drawRoundedRect(QRectF(0, 0, 46, 46), 16, 16)
        icon = QRectF(12, 12, 22, 22)
        if self._lit:
            glow = QRadialGradient(QPointF(23, 22), 18)
            glow.setColorAt(0, QColor(255, 196, 60, 210))
            glow.setColorAt(1, QColor(255, 196, 60, 0))
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QRectF(4, 4, 38, 38))
            _paint_icon(painter, "lightbulb-fill", icon, "#f0b429")
        else:
            _paint_icon(painter, "lightbulb", icon, "#0d1e35")
        painter.end()


class HyperionWindow(GlassWindow):
    def __init__(self) -> None:
        super().__init__()
        self._connected = False
        self._strip = DEFAULT_INSTANCE
        self._devices: list[tuple[int, str]] = []
        self._modes: list[str] = []
        self._server_modes: list[str] = []
        self._lit: set[int] = set()
        self._rgb = (255, 168, 72)
        self._brightness = 100
        self._source = "effect"
        self._color_lock = 0.0
        self._mode_until = 0.0
        self._power_until = 0.0
        self._pump: _ScreenPump | None = None
        self._fit = StripFit()
        self._counts: dict[str, QSpinBox] = {}
        self._sliders: dict[str, QSlider] = {}
        self._values: dict[str, QLabel] = {}
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.setInterval(90)
        self._send_timer.timeout.connect(self._send_now)
        self._link = HyperionThread()
        self._link.linked.connect(self._on_linked)
        self._link.note.connect(self._log)
        self._link.failed.connect(self._on_failed)
        self._link.strips.connect(self._show_strips)
        self._link.modes.connect(self._show_modes)
        self._link.live.connect(self._show_live)
        self._watch = QTimer(self)
        self._watch.setInterval(2000)
        self._watch.timeout.connect(self._watch_strip)
        self._link.start()
        self._build()
        self._quitting = False
        self._load()
        self._set_linked(False, "")
        self.setFocus()
        self._install_tray()
        QTimer.singleShot(0, self._connect_last)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        root.setSpacing(0)
        root.addWidget(self.header_bar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("glassBody")
        prefer = str(QSettings().value("hyperion_host", DEFAULT_HOST))
        self.search_page = SearchPage(prefer)
        self.search_page.chosen.connect(self._pick_server)
        self.search_page.manual.connect(lambda: self.stack.setCurrentIndex(1))
        self._net = QTimer(self)
        self._net.timeout.connect(self._refresh_network)
        self._net.start(2000)
        self._refresh_network()
        self.stack.addWidget(self.search_page)
        self.stack.addWidget(self._connection_page())
        self.stack.addWidget(self._color_page())
        self.stack.addWidget(self._settings_page())
        root.addWidget(self.stack, 1)

    def _connection_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 8, 24, 16)
        layout.setSpacing(8)

        self.host = QLineEdit()
        self.host.setPlaceholderText("Адрес")
        self.host.setToolTip("Адрес")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(DEFAULT_PORT)
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.port.setToolTip("Порт")
        address = QHBoxLayout()
        address.setSpacing(8)
        address.addWidget(self._shell("globe", self.host), 1)
        port_shell = self._shell("ethernet", self.port)
        port_shell.setFixedWidth(112)
        address.addWidget(port_shell)
        layout.addLayout(address)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Пароль")
        self.password.setToolTip("Пароль")
        self.reveal = _EyeButton()
        self.reveal.toggled.connect(self._toggle_password)
        layout.addWidget(self._shell("lock", self.password, self.reveal))

        layout.addStretch(1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        self.status.setVisible(False)
        layout.addWidget(self.status)

        self.connect_button = QPushButton("Подключить")
        self.connect_button.setObjectName("composer")
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_button)

        back = QPushButton("Назад к поиску")
        back.setObjectName("textButton")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignHCenter)
        return page

    def _color_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(22, 4, 22, 10)
        outer.setSpacing(4)

        outer.addWidget(self._field("Прибор"))
        self.device = _DevicePicker()
        self.device.set_name("Прибор")
        self.device.clicked.connect(self._open_devices)
        self.lamp = _LampButton()
        self.lamp.clicked.connect(self._toggle_power)
        self._device_menu = _DeviceMenu()
        self._device_menu.chosen.connect(self._choose_device)
        device_row = QHBoxLayout()
        device_row.setSpacing(8)
        device_row.addWidget(self.device, 1)
        device_row.addWidget(self.lamp)
        outer.addLayout(device_row)

        mode_head = QHBoxLayout()
        mode_head.setSpacing(8)
        mode_head.addWidget(self._field("Режим"))
        mode_head.addStretch(1)
        self.settings_button = QPushButton("Настройки")
        self.settings_button.setObjectName("textButton")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self._open_settings)
        mode_head.addWidget(self.settings_button)
        outer.addLayout(mode_head)
        self.mode = _DevicePicker()
        self.mode.set_name("Режим")
        self.mode.clicked.connect(self._open_modes)
        self._mode_menu = _DeviceMenu()
        self._mode_menu.chosen.connect(self._choose_mode)
        outer.addWidget(self.mode)
        self.screen_hint = QLabel("")
        self.screen_hint.setObjectName("hint")
        self.screen_hint.setWordWrap(True)
        self.screen_hint.setVisible(False)
        outer.addWidget(self.screen_hint)
        self._mode = ""

        self.bright = _BrightBar()
        self.bright.changed.connect(self._on_brightness)
        outer.addWidget(self.bright)

        color_head = QHBoxLayout()
        color_head.setSpacing(8)
        color_head.addWidget(self._field("Цвет"))
        color_head.addStretch(1)
        self.hex_label = QLabel("#FFA848")
        self.hex_label.setObjectName("count")
        color_head.addWidget(self.hex_label)
        outer.addLayout(color_head)

        self.wheel = _ColorWheel()
        self.wheel.chosen.connect(self._on_wheel)
        outer.addWidget(self.wheel, 0, Qt.AlignmentFlag.AlignHCenter)
        self.swatches = _Swatches(PRESETS)
        self.swatches.chosen.connect(self._on_swatch)
        outer.addWidget(self.swatches)
        channels = QWidget()
        channels.setObjectName("inputShell")
        channel_box = QVBoxLayout(channels)
        channel_box.setContentsMargins(14, 8, 12, 8)
        channel_box.setSpacing(0)
        for key, caption, fill in (
            ("r", "R", "#ff5f57"),
            ("g", "G", "#28c840"),
            ("b", "B", "#4d88ff"),
        ):
            channel_box.addLayout(self._channel(key, caption, fill))
        outer.addWidget(channels)
        self._apply_rgb(self._rgb, send=False)
        outer.addStretch(1)

        self.back_button = QPushButton("Назад")
        self.back_button.setObjectName("textButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._toggle_connection)
        outer.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignHCenter)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 4, 22, 12)
        layout.setSpacing(6)

        layout.addWidget(self._field("Диоды"))
        grid = QWidget()
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(6)
        for index, (key, title, default) in enumerate(
            (("left", "Слева", 0), ("top", "Сверху", 0), ("right", "Справа", 0), ("bottom", "Снизу", 27))
        ):
            cell = QWidget()
            cell_box = QVBoxLayout(cell)
            cell_box.setContentsMargins(0, 0, 0, 0)
            cell_box.setSpacing(2)
            cell_box.addWidget(self._field(title))
            spin = QSpinBox()
            spin.setRange(0, 400)
            spin.setValue(default)
            spin.valueChanged.connect(lambda _value, name=key: self._fit_changed(name))
            cell_box.addWidget(spin)
            self._counts[key] = spin
            grid_layout.addWidget(cell, index // 2, index % 2)
        layout.addWidget(grid)

        note = QLabel("Диод 1 — правый край стола, дальше цепочка идёт влево.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(self._field("Область захвата"))
        self.capture = _RangeBar()
        self.capture.changed.connect(lambda _start, _end: self._fit_changed("capture"))
        layout.addWidget(self.capture)
        layout.addWidget(self._field("Диапазон ленты"))
        self.span = _RangeBar()
        self.span.changed.connect(lambda _start, _end: self._fit_changed("span"))
        layout.addWidget(self.span)
        self.span_label = QLabel("Захват и лента задаются одинаковым диапазоном.")
        self.span_label.setObjectName("hint")
        self.span_label.setWordWrap(True)
        layout.addWidget(self.span_label)

        layout.addStretch(1)
        done = QPushButton("Готово")
        done.setObjectName("composer")
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.clicked.connect(self._close_settings)
        layout.addWidget(done)
        return page

    def _shell(self, icon: str, field: QWidget, trailing: QWidget | None = None) -> QWidget:
        shell = QWidget()
        shell.setObjectName("inputShell")
        row = QHBoxLayout(shell)
        row.setContentsMargins(12, 2, 6 if trailing else 12, 2)
        row.setSpacing(6)
        row.addWidget(_Glyph(icon), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(field, 1)
        if trailing is not None:
            row.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
        shell.mousePressEvent = lambda _event, target=field: target.setFocus()
        return shell

    def _field(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("field")
        return label

    def _channel(self, key: str, caption: str, fill: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(caption)
        name.setFixedWidth(18)
        name.setStyleSheet("color: #0d1e35; font-size: 15px; font-weight: 600; background: transparent;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 255)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: rgba(13,30,53,0.14); border: none; border-radius: 2px; }"
            f"QSlider::sub-page:horizontal {{ background: {fill}; border: none; border-radius: 2px; }}"
            "QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0;"
            " background: #0d1e35; border: none; border-radius: 7px; }"
        )
        slider.valueChanged.connect(lambda _value, channel=key: self._on_slider(channel))
        value = QLabel("0")
        value.setFixedWidth(36)
        value.setStyleSheet("color: #0d1e35; font-size: 15px; font-weight: 600; background: transparent;")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(name)
        row.addWidget(slider, 1)
        row.addWidget(value)
        self._sliders[key] = slider
        self._values[key] = value
        return row

    def _load(self) -> None:
        settings = QSettings()
        self.host.setText(str(settings.value("hyperion_host", DEFAULT_HOST)))
        self.port.setValue(int(settings.value("hyperion_port", DEFAULT_PORT)))
        self.password.setText(str(settings.value("hyperion_password", DEFAULT_PASSWORD)))
        self._strip = int(settings.value("hyperion_instance", DEFAULT_INSTANCE))
        values = {
            "top": int(settings.value("hyperion_leds_top", 0)),
            "bottom": int(settings.value("hyperion_leds_bottom", 27)),
            "left": int(settings.value("hyperion_leds_left", 0)),
            "right": int(settings.value("hyperion_leds_right", 0)),
        }
        for key, value in values.items():
            spin = self._counts[key]
            spin.blockSignals(True)
            spin.setValue(max(0, min(400, value)))
            spin.blockSignals(False)
        saved_percent = int(settings.value("hyperion_bottom_percent", 15))
        capture_start = settings.value("hyperion_capture_start", None)
        capture_end = settings.value("hyperion_capture_end", None)
        if capture_start is None or capture_end is None:
            capture_start = max(0, 100 - saved_percent)
            capture_end = 100
        self.capture.set_values(int(capture_start), int(capture_end))
        start = settings.value("hyperion_span_start", None)
        end = settings.value("hyperion_span_end", None)
        if start is None or end is None:
            start = int(settings.value("hyperion_inset_left", 0))
            end = 100 - int(settings.value("hyperion_inset_right", 0))
        self.span.set_values(int(start), int(end))
        self._push_fit(save=False)

    def _save(self) -> None:
        settings = QSettings()
        settings.setValue("hyperion_host", self.host.text().strip())
        settings.setValue("hyperion_port", self.port.value())
        settings.setValue("hyperion_password", self.password.text())
        settings.setValue("hyperion_instance", self._strip)
        settings.setValue("hyperion_leds_top", self._counts["top"].value())
        settings.setValue("hyperion_leds_bottom", self._counts["bottom"].value())
        settings.setValue("hyperion_leds_left", self._counts["left"].value())
        settings.setValue("hyperion_leds_right", self._counts["right"].value())
        capture_start, capture_end = self.capture.values()
        settings.setValue("hyperion_capture_start", capture_start)
        settings.setValue("hyperion_capture_end", capture_end)
        settings.setValue("hyperion_bottom_percent", max(1, capture_end - capture_start))
        start, end = self.span.values()
        settings.setValue("hyperion_span_start", start)
        settings.setValue("hyperion_span_end", end)

    def _open_settings(self) -> None:
        self._refresh_span()
        self.stack.setCurrentIndex(3)

    def _close_settings(self) -> None:
        self._save()
        self.stack.setCurrentIndex(2)

    def _fit_changed(self, key: str | None = None) -> None:
        del key
        self._push_fit(save=True)

    def _push_fit(self, save: bool) -> None:
        self._fit.update(
            top=self._counts["top"].value(),
            bottom=self._counts["bottom"].value(),
            left=self._counts["left"].value(),
            right=self._counts["right"].value(),
            percent=max(1, self.capture.values()[1] - self.capture.values()[0]),
            span_start=self.span.values()[0],
            span_end=self.span.values()[1],
            mark=False,
            capture_start=self.capture.values()[0],
            capture_end=self.capture.values()[1],
        )
        self._refresh_span()
        if save:
            self._save()

    def _refresh_span(self) -> None:
        start, end = self.span.values()
        capture_start, capture_end = self.capture.values()
        total = max(
            1,
            self._counts["top"].value()
            + self._counts["bottom"].value()
            + self._counts["left"].value()
            + self._counts["right"].value(),
        )
        if total == 1:
            left_at = right_at = 0
        else:
            left_at = int(round(start / 100 * (total - 1)))
            right_at = int(round(end / 100 * (total - 1)))
        if right_at < left_at:
            right_at = left_at
        first = total - right_at
        last = total - left_at
        self.span_label.setText(
            f"Экран {capture_start}–{capture_end}% идёт на диоды {first}–{last}. Остальные гаснут."
        )

    def _toggle_password(self, shown: bool) -> None:
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.reveal.setToolTip("Скрыть пароль" if shown else "Показать пароль")

    def _connect_last(self) -> None:
        """При запуске сразу открыть сервер, к которому подключались в прошлый раз."""
        if self._connected:
            return
        app = QApplication.instance()
        if app is not None and "--selftest" in app.arguments():
            return
        if not QSettings().contains("hyperion_host"):
            return
        if not self.host.text().strip():
            return
        self.stack.setCurrentIndex(1)
        self._toggle_connection()

    def _toggle_connection(self) -> None:
        if self._connected:
            self._stop_screen()
            self.connect_button.setEnabled(False)
            self.back_button.setEnabled(False)
            self._set_status("Отключение…", "busy")
            self._link.submit(("disconnect",))
            return
        host = self.host.text().strip()
        if not host:
            self._set_status("Укажите адрес сервера", "bad")
            return
        self._save()
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Подключение…")
        self._lock_server(True)
        self._set_status("Подключение…", "busy")
        self._link.submit(("connect", host, self.port.value(), self.password.text()))

    def _on_linked(self, connected: bool, message: str) -> None:
        self._set_linked(connected, message)

    def _on_failed(self, message: str) -> None:
        if not self._connected:
            self.connect_button.setEnabled(True)
            self.connect_button.setText("Подключить")
            self._lock_server(False)
            self.stack.setCurrentIndex(1)
        self.back_button.setEnabled(True)
        self._set_status(message, "bad")

    def _set_linked(self, connected: bool, message: str) -> None:
        self._connected = connected
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Подключить")
        self.back_button.setEnabled(True)
        self._lock_server(False)
        if connected:
            self.stack.setCurrentIndex(2)
            self._watch.start()
            self._link.submit(("peek", self._strip))
        elif self.stack.currentIndex() in {2, 3}:
            self.stack.setCurrentIndex(1)
        if not connected:
            self._stop_screen()
            self._watch.stop()
            self._lit.clear()
            self._mode = ""
            self.lamp.set_lit(False)
            self._set_screen_hint("")
        if connected:
            kind = "ok"
        elif not message or message == "Отключено":
            kind = "idle"
        else:
            kind = "bad"
        self._set_status(message, kind)

    def _lock_server(self, locked: bool) -> None:
        for widget in (self.host, self.port, self.password, self.reveal):
            widget.setEnabled(not locked)

    def _set_status(self, text: str, kind: str) -> None:
        colors = {
            "idle": "rgba(255, 255, 255, 0.62)",
            "busy": "#b9ccff",
            "ok": "rgba(255, 255, 255, 0.92)",
            "bad": "#ffb0a8",
        }
        style = f"color: {colors.get(kind, 'rgba(255,255,255,0.62)')}; font-size: 12px;"
        self.status.setText(text)
        self.status.setStyleSheet(style)
        self.status.setVisible(bool(text))

    def _show_strips(self, strips: list) -> None:
        self._devices = [(int(number), str(name)) for number, name in strips]
        chosen = self._devices[0] if self._devices else (self._strip, "Прибор")
        for number, name in self._devices:
            if number == self._strip:
                chosen = (number, name)
                break
        self._strip = chosen[0]
        self.device.set_name(chosen[1])
        self.lamp.set_lit(self._strip in self._lit)
        if self._connected:
            self._link.submit(("peek", self._strip))

    def _is_tv(self, number: int | None = None) -> bool:
        number = self._strip if number is None else int(number)
        for item, label in self._devices:
            if item == number:
                return label.replace("\u200b", "").strip() == "Телевизор"
        return number == 0

    def _follow_capture(self) -> None:
        """На телевизоре картинка только в «Адаптив». Иначе цвет и эффекты, как с телефона."""
        if not self._connected or not self._is_tv():
            return
        self._link.submit(("capture", self._mode == TV_ADAPTIVE, self._strip))

    def _is_desk(self, number: int | None = None) -> bool:
        number = self._strip if number is None else int(number)
        for item, label in self._devices:
            if item == number:
                return label.replace("\u200b", "").strip() == DESK_NAME
        return number == DEFAULT_INSTANCE

    def _apply_modes(self) -> None:
        """Как в Home Assistant: на столе «Адаптив» — экран, на телевизоре — захват."""
        names: list[str] = []
        desk_names = {TV_ADAPTIVE, LEGACY_SCREEN, SCREEN_MODE, "адаптив"}
        for raw in self._server_modes:
            name = str(raw).strip()
            if not self._is_desk() and name in {LEGACY_SCREEN, "адаптив"}:
                continue
            if self._is_desk() and name in desk_names:
                name = SCREEN_MODE
            if not name or name in names:
                continue
            names.append(name)
        if self._is_desk() and SCREEN_MODE not in names:
            spot = 1 if names and names[0] == SOLID else 0
            names.insert(spot, SCREEN_MODE)
        if SOLID not in names:
            names.insert(0, SOLID)
        self._modes = names
        if self._mode == LEGACY_SCREEN:
            self._mode = SCREEN_MODE
        if self._mode not in self._modes:
            self._mode = SOLID if SOLID in self._modes else (self._modes[0] if self._modes else "")
        self.mode.set_name(self._mode or "Нет режимов")

    def _show_modes(self, names: list) -> None:
        self._server_modes = [str(raw).strip() for raw in names if str(raw).strip()]
        self._apply_modes()

    def _open_devices(self) -> None:
        if not self._devices:
            return
        names = [name for _number, name in self._devices]
        current = next((name for number, name in self._devices if number == self._strip), names[0])
        self._device_menu.present(self.device, names, current)

    def _open_modes(self) -> None:
        if not self._modes:
            return
        self._mode_menu.present(self.mode, self._modes, self._mode)

    def _choose_device(self, name: str) -> None:
        for number, label in self._devices:
            if label == name:
                self._strip = number
                self.device.set_name(label)
                break
        self.lamp.set_lit(self._strip in self._lit)
        self._apply_modes()
        if not self._is_desk() and self._source == "screen":
            self._stop_screen()
        self._save()
        if self._connected:
            self._link.submit(("peek", self._strip))

    def _choose_mode(self, name: str) -> None:
        now = time.monotonic()
        self._color_lock = now + 0.6
        self._mode_until = now + 3.0
        self._mode = name
        self.mode.set_name(name)
        self._set_screen_hint("")
        if name != SCREEN_MODE:
            self._stop_screen()
        if name == SOLID:
            self._source = "color"
            self._mode_until = time.monotonic() + 8.0
            if self._connected:
                self._lit.add(self._strip)
                self.lamp.set_lit(True)
                self._power_until = time.monotonic() + 4.0
                self._link.client._force_show = True
                self._link.submit(("wake", self._strip))
                self._link.submit(("color", self._output_rgb(), DEFAULT_PRIORITY, self._strip))
                self._follow_capture()
            return
        if self._is_desk() and name in {SCREEN_MODE, TV_ADAPTIVE, LEGACY_SCREEN, "адаптив"}:
            self._source = "screen"
            self._mode = SCREEN_MODE
            self.mode.set_name(SCREEN_MODE)
            self._stop_screen()
            if self._connected:
                self._lit.add(self._strip)
                self.lamp.set_lit(True)
                self._power_until = time.monotonic() + 4.0
                self._link.submit(("wake", self._strip))
                self._link.submit(("effect", TV_ADAPTIVE, self._strip))
            return
        self._source = "effect"
        if not self._connected:
            return
        if self._strip not in self._lit:
            self._lit.add(self._strip)
            self.lamp.set_lit(True)
            self._link.submit(("wake", self._strip))
        self._link.submit(("effect", name, self._strip))
        self._follow_capture()

    def _use_solid(self) -> None:
        if time.monotonic() < self._color_lock:
            return
        self._stop_screen()
        self._mode_until = time.monotonic() + 3.0
        self._mode = SOLID
        self._source = "color"
        if hasattr(self, "mode"):
            self.mode.set_name(SOLID)

    def _set_screen_hint(self, text: str) -> None:
        self.screen_hint.setText(text)
        self.screen_hint.setVisible(bool(text))

    def _begin_screen(self) -> None:
        if not self._connected:
            return
        self._set_screen_hint("")
        self.raise_()
        self.activateWindow()
        granted = request_screen_access()
        if not granted:
            self._set_screen_hint("Разрешите Hyperion запись экрана в настройках системы")
            open_screen_settings()
            return
        self._lit.add(self._strip)
        self.lamp.set_lit(True)
        self._power_until = time.monotonic() + 4.0
        self._link.submit(("wake", self._strip))
        self._start_screen()

    def _start_screen(self) -> None:
        pump = self._pump
        if pump is not None and pump.isRunning():
            return
        pump = _ScreenPump(self._link.client, self._strip, self._fit)
        pump.failed.connect(self._screen_failed)
        self._pump = pump
        pump.start()

    def _stop_screen(self) -> None:
        pump = self._pump
        self._pump = None
        if pump is None:
            return
        pump.request_stop()
        if pump.isRunning():
            pump.wait(2000)

    def _screen_failed(self, message: str) -> None:
        self._stop_screen()
        text = (message or "").strip()
        if "отклонил" in text or "захват" in text.lower():
            self._set_screen_hint("Разрешите Hyperion запись экрана в настройках системы")
            open_screen_settings()
            return
        self._set_screen_hint(text or "Hyperion не принял экран")

    def _toggle_power(self) -> None:
        if not self._connected:
            return
        self._power_until = time.monotonic() + 4.0
        if self._strip in self._lit:
            self._stop_screen()
            self._lit.discard(self._strip)
            self.lamp.set_lit(False)
            self._link.submit(("blank", self._strip))
            return
        if self._is_desk() and (
            self._source == "screen" or self._mode in {SCREEN_MODE, TV_ADAPTIVE, LEGACY_SCREEN, "адаптив"}
        ):
            self._lit.add(self._strip)
            self.lamp.set_lit(True)
            self._link.submit(("wake", self._strip))
            self._link.submit(("effect", TV_ADAPTIVE, self._strip))
            return
        self._lit.add(self._strip)
        self.lamp.set_lit(True)
        self._link.submit(("wake", self._strip))
        if self._source == "color" or self._mode == SOLID or self._mode not in self._modes:
            self._use_solid()
            self._link.submit(("color", self._output_rgb(), DEFAULT_PRIORITY, self._strip))
        elif self._mode:
            self._link.submit(("effect", self._mode, self._strip))
        self._follow_capture()

    def _show_live(self, state: dict) -> None:
        if int(state.get("instance", -1)) != self._strip:
            return
        if self.wheel._drag or self._send_timer.isActive():
            return
        on = bool(state.get("on"))
        if time.monotonic() >= self._power_until:
            if on:
                self._lit.add(self._strip)
            else:
                self._lit.discard(self._strip)
            self.lamp.set_lit(on)
        if self.screen_hint.isVisible() and self._mode == SCREEN_MODE:
            return
        mode = str(state.get("mode") or "")
        if self._is_desk() and mode in {SCREEN_MODE, TV_ADAPTIVE, LEGACY_SCREEN, "Ноутбук"}:
            mode = SCREEN_MODE
        elif mode == LEGACY_SCREEN:
            mode = SCREEN_MODE
        if mode and mode != self._mode and time.monotonic() < self._mode_until:
            return
        if self._mode == SOLID and self._source == "color" and mode == SCREEN_MODE:
            return
        screen_on = self._pump is not None and self._pump.isRunning()
        desk_screen = self._is_desk() and mode == SCREEN_MODE and on
        if desk_screen:
            self._mode = SCREEN_MODE
            self._source = "screen"
            self.mode.set_name(SCREEN_MODE)
            if screen_on:
                self._stop_screen()
            return
        if screen_on and time.monotonic() >= self._power_until:
            self._stop_screen()
            self._source = "effect"
        if mode:
            self._mode = mode
            self._source = "color" if mode == SOLID else "effect"
            self.mode.set_name(mode)
        rgb = state.get("rgb")
        if mode == SOLID and isinstance(rgb, (tuple, list)) and len(rgb) == 3:
            self._apply_rgb((int(rgb[0]), int(rgb[1]), int(rgb[2])), send=False)
            self._source = "color"
            self._mode = SOLID
            self.mode.set_name(SOLID)

    def _watch_strip(self) -> None:
        if not self._connected or self.wheel._drag or self._send_timer.isActive():
            return
        self._link.submit(("peek", self._strip))

    def _on_brightness(self, value: int) -> None:
        if time.monotonic() < self._color_lock:
            self.bright.set_value(self._brightness)
            return
        self._brightness = value
        self._use_solid()
        self._schedule_send()

    def _on_wheel(self, red: int, green: int, blue: int) -> None:
        self._apply_rgb((red, green, blue))

    def _on_swatch(self, red: int, green: int, blue: int) -> None:
        self._apply_rgb((red, green, blue))

    def _on_slider(self, _channel: str) -> None:
        self._apply_rgb(
            (
                self._sliders["r"].value(),
                self._sliders["g"].value(),
                self._sliders["b"].value(),
            )
        )

    def _output_rgb(self) -> tuple[int, int, int]:
        scale = self._brightness / 100
        return tuple(max(0, min(255, round(part * scale))) for part in self._rgb)

    def _apply_rgb(self, rgb: tuple[int, int, int], send: bool = True) -> None:
        if send and time.monotonic() < self._color_lock:
            return
        self._rgb = (
            max(0, min(255, int(rgb[0]))),
            max(0, min(255, int(rgb[1]))),
            max(0, min(255, int(rgb[2]))),
        )
        for key, value in zip(("r", "g", "b"), self._rgb):
            slider = self._sliders[key]
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self._paint()
        if send:
            self._use_solid()
            self._link.client._force_show = True
            self._schedule_send()

    def _paint(self) -> None:
        red, green, blue = self._rgb
        self.hex_label.setText(f"#{red:02X}{green:02X}{blue:02X}")
        if not self.wheel._drag:
            self.wheel.set_color(self._rgb)
        self.swatches.set_current(self._rgb)
        self.bright.set_color(self._rgb)
        for key, value in zip(("r", "g", "b"), self._rgb):
            self._values[key].setText(str(value))

    def _schedule_send(self) -> None:
        if self._connected and self._strip in self._lit:
            self._send_timer.start()

    def _send_now(self) -> None:
        self._send_timer.stop()
        if not self._connected or self._strip not in self._lit or self._source != "color":
            return
        self._link.client._force_show = True
        self._link.submit(("color", self._output_rgb(), DEFAULT_PRIORITY, self._strip))
        self._follow_capture()

    def _clear(self) -> None:
        if not self._connected:
            return
        self._lit.discard(self._strip)
        self.lamp.set_lit(False)
        self._link.submit(("clear", self._strip, not self._lit))

    def _log(self, text: str) -> None:
        if text.startswith("На ленте") or text.startswith("Подключено"):
            self._set_status(text, "ok")
        elif self._connected and text.startswith("Лента погашена"):
            self._set_status("На связи, лента погашена", "ok")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_search_armed", False):
            return
        self._search_armed = True
        QTimer.singleShot(700, self.search_page.retry)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.search_page.retry()

    def _refresh_network(self) -> None:
        self.network.set_online(network_is_up())

    def _pick_server(self, host: str, port: int) -> None:
        self.host.setText(host)
        self.port.setValue(port)
        self._save()
        self.stack.setCurrentIndex(1)

    def closeEvent(self, event) -> None:
        if not self._quitting:
            self._save()
            self.hide()
            event.ignore()
            return
        self._save()
        self._stop_screen()
        self.search_page.stop()
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.hide()
        self._link.request_stop()
        self._link.wait(4000)
        super().closeEvent(event)

    def _capture_running(self) -> bool:
        pump = self._pump
        if pump is not None and pump.isRunning():
            return True
        return Path("/tmp/ampilight-capturing").exists()

    def _refresh_tray_icon(self) -> None:
        capturing = self._capture_running()
        if not capturing:
            self._tray_phase = (self._tray_phase + 6) % 360
        elif self._tray_capturing:
            return
        self._tray_capturing = capturing
        self._tray.setIcon(self._menu_icon(capturing, self._tray_phase))
        if hasattr(self, "_capture_button"):
            self._capture_button.setText("Остановить" if capturing else "Запустить")

    def _menu_icon(self, capturing: bool, phase: float = 0) -> QIcon:
        """Квадратный телевизор на высоту строки меню. Широкий кадр система сплющивает."""
        pixmap = QPixmap(44, 44)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        screen = QRectF(1, 1, 20, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        if capturing:
            painter.setBrush(QColor(191, 90, 242))
        else:
            painter.setBrush(QBrush(glow_gradient(screen.center(), phase)))
        painter.drawRoundedRect(screen, 2.5, 2.5)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(9.2, 15.4, 3.6, 1.6), 0.6, 0.6)
        painter.drawRoundedRect(QRectF(6.2, 17.2, 9.6, 1.8), 0.7, 0.7)
        font = QFont("Helvetica Neue")
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(screen, int(Qt.AlignmentFlag.AlignCenter), "H")
        painter.end()
        return QIcon(pixmap)

    def _install_tray(self) -> None:
        self._tray_capturing = False
        self._tray_phase = 0.0
        self._tray = QSystemTrayIcon(self._menu_icon(False), self)
        self._tray.setToolTip("Hyperion")
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()
        self._capture_panel = self._build_capture_panel()
        self._tray_timer = QTimer(self)
        self._tray_timer.setInterval(70)
        self._tray_timer.timeout.connect(self._refresh_tray_icon)
        self._tray_timer.start()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self._refresh_preview)

    def _build_capture_panel(self) -> QWidget:
        panel = QWidget(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        panel.setObjectName("hyperionTray")
        panel.setStyleSheet("QWidget#hyperionTray { background: #1c1c22; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self._preview = QLabel("Захват выключен")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(248, 78)
        self._preview.setStyleSheet(
            "background: #0d1e35; color: white; border-radius: 10px; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(self._preview)
        self._capture_button = QPushButton("Запустить")
        self._capture_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capture_button.clicked.connect(self._toggle_capture)
        open_button = QPushButton("Открыть")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._show_from_tray)
        quit_button = QPushButton("Выйти")
        quit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_button.clicked.connect(self._quit_from_tray)
        for button in (self._capture_button, open_button, quit_button):
            button.setStyleSheet(
                "QPushButton { background: white; color: #16161c; border: none; border-radius: 10px;"
                " padding: 8px 12px; font-size: 14px; font-weight: 600; }"
            )
            layout.addWidget(button)
        panel.adjustSize()
        self._clip_tray_panel(panel)
        return panel

    def _clip_tray_panel(self, panel: QWidget | None = None) -> None:
        target = self._capture_panel if panel is None else panel
        path = QPainterPath()
        path.addRoundedRect(QRectF(target.rect()), 16, 16)
        target.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _refresh_preview(self) -> None:
        if not self._capture_panel.isVisible():
            return
        capturing = self._capture_running()
        self._capture_button.setText("Остановить" if capturing else "Запустить")
        image = QImage(str(Path("/tmp/ampilight-preview.ppm")))
        if capturing and not image.isNull():
            pixmap = QPixmap.fromImage(image).scaled(
                248,
                78,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview.setPixmap(pixmap)
            return
        self._preview.setPixmap(QPixmap())
        self._preview.setText("Захват включён" if capturing else "Захват выключен")

    def _toggle_capture(self) -> None:
        if self._capture_running():
            self._lit.discard(1)
            self._link.submit(("blank", 1))
            if self._strip == 1:
                self.lamp.set_lit(False)
            return
        self._lit.add(1)
        self._link.submit(("wake", 1))
        self._link.submit(("effect", TV_ADAPTIVE, 1))
        if self._strip == 1:
            self.lamp.set_lit(True)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self._show_capture_panel()
            return
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._show_capture_panel()

    def _show_capture_panel(self) -> None:
        self._refresh_preview()
        panel = self._capture_panel
        panel.adjustSize()
        self._clip_tray_panel()
        icon = self._tray.geometry()
        cursor = QCursor.pos()
        if icon.isValid() and icon.width() > 4 and icon.height() > 4:
            anchor = icon
        else:
            anchor = QRect(cursor.x() - 11, cursor.y() - 11, 22, 22)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else panel.rect()
        if anchor.center().x() > area.center().x():
            x = anchor.right() - panel.width()
        else:
            x = anchor.left()
        y = anchor.bottom() + 4
        x = max(area.left() + 6, min(x, area.right() - panel.width() - 6))
        if y + panel.height() > area.bottom() - 6:
            y = max(area.top() + 4, anchor.top() - panel.height() - 4)
        panel.move(int(x), int(y))
        panel.show()
        panel.raise_()
        self._preview_timer.start()

    def _show_from_tray(self) -> None:
        self._capture_panel.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._quitting = True
        self._capture_panel.hide()
        self.close()
