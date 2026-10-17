"""Окно в духе чата M.A.I.A: стекло на всю площадь, светофор, капсула внизу."""

from __future__ import annotations

import ctypes
import sys
from ctypes import c_bool, c_char_p, c_double, c_long, c_void_p

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QFont, QFontMetrics, QPainter, QPainterPath, QPen

from app.i18n import tr
from PyQt6.QtWidgets import QApplication, QComboBox, QGridLayout, QLineEdit, QPushButton, QSpinBox, QWidget

RADIUS = 26
SHADOW = 0
COMPACT = (360, 600)
EXPANDED = (640, 720)
NAVY = QColor(13, 30, 53)
ACCENT = QColor(77, 136, 255)

GLASS_STYLE = """
QWidget, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}
QLabel { color: rgba(255, 255, 255, 0.92); background: transparent; }
QLabel#field { color: rgba(255, 255, 255, 0.68); font-size: 12px; }
QLabel#hint { color: rgba(255, 255, 255, 0.62); font-size: 12px; }
QLabel#count { color: rgba(255, 255, 255, 0.92); font-size: 13px; font-weight: 600; }
QLineEdit, QSpinBox {
    background: rgba(245, 245, 247, 0.94);
    color: #0d1e35;
    border: 2px solid transparent;
    border-radius: 16px;
    padding: 8px 14px;
    min-height: 22px;
    font-size: 15px;
    selection-background-color: #4d88ff;
    selection-color: white;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: transparent; }
QPushButton#device {
    background: rgba(245, 245, 247, 0.94);
    color: #0d1e35;
    border: none;
    border-radius: 16px;
    text-align: left;
    padding: 0 36px 0 14px;
    font-size: 15px;
    font-weight: 600;
}
QPushButton#device:hover { background: white; }
QWidget#inputShell {
    background: rgba(245, 245, 247, 0.94);
    border-radius: 16px;
}
QWidget#inputShell QLineEdit, QWidget#inputShell QSpinBox {
    background: transparent;
    border: none;
    padding: 8px 2px;
    min-height: 22px;
}
QWidget#inputShell QSpinBox::up-button, QWidget#inputShell QSpinBox::down-button { width: 0; height: 0; }
QPushButton#eye {
    background: transparent;
    border: none;
    padding: 0;
    min-width: 28px;
    max-width: 28px;
}
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; }
QCheckBox { color: rgba(255, 255, 255, 0.88); spacing: 8px; background: transparent; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 0.45);
    background: transparent;
}
QCheckBox::indicator:checked { background: #f5f5f7; border-color: #f5f5f7; }
QPushButton#composer {
    background: rgba(245, 245, 247, 0.94);
    color: #0d1e35;
    border: none;
    border-radius: 26px;
    font-size: 16px;
    font-weight: 600;
    min-height: 52px;
    padding: 0 18px;
}
QPushButton#composer:hover { background: white; }
QPushButton#composer:disabled { background: rgba(245, 245, 247, 0.45); color: rgba(13, 30, 53, 0.45); }
QPushButton#textButton {
    background: transparent;
    color: rgba(255, 255, 255, 0.82);
    border: none;
    font-size: 13px;
    font-weight: 500;
    padding: 4px 2px;
}
QPushButton#textButton:hover { color: white; }
QPushButton#strip {
    background: transparent;
    color: rgba(255, 255, 255, 0.82);
    border: 1px solid rgba(255, 255, 255, 0.35);
    border-radius: 14px;
    font-size: 13px;
    font-weight: 600;
    padding: 6px 12px;
}
QPushButton#strip:checked {
    background: rgba(245, 245, 247, 0.94);
    color: #0d1e35;
    border-color: transparent;
}
QPushButton#server {
    background: rgba(245, 245, 247, 0.92);
    color: #0d1e35;
    border: none;
    border-radius: 16px;
    text-align: left;
    padding: 0;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#server QLabel { background: transparent; color: #0d1e35; }
QPushButton#server QLabel#serverHost { color: rgba(13, 30, 53, 0.55); font-size: 12px; font-weight: 500; }
QPushButton#server:hover { background: white; }
QPushButton#mode {
    background: rgba(245, 245, 247, 0.92);
    color: #0d1e35;
    border: none;
    border-radius: 14px;
    text-align: left;
    padding: 12px 14px;
    font-size: 15px;
    font-weight: 600;
}
QPushButton#mode:hover { background: white; }
QPushButton#mode[active="true"] { background: white; }
QSlider::groove:horizontal { height: 4px; background: rgba(255, 255, 255, 0.28); border-radius: 2px; }
QSlider::sub-page:horizontal { background: rgba(245, 245, 247, 0.92); border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: white;
    border-radius: 8px;
}
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.35); border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPlainTextEdit {
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.72);
    font-size: 12px;
}
"""


def _objc():
    lib = getattr(_objc, "lib", None)
    if lib is None:
        lib = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        lib.objc_getClass.restype = c_void_p
        lib.objc_getClass.argtypes = [c_char_p]
        lib.sel_registerName.restype = c_void_p
        lib.sel_registerName.argtypes = [c_char_p]
        lib.object_getClassName.restype = c_char_p
        lib.object_getClassName.argtypes = [c_void_p]
        _objc.lib = lib
    return lib


def _sel(name: str) -> c_void_p:
    return _objc().sel_registerName(name.encode())


def _cls(name: str) -> c_void_p:
    return _objc().objc_getClass(name.encode())


class _NSRect(ctypes.Structure):
    _fields_ = (
        ("x", c_double),
        ("y", c_double),
        ("width", c_double),
        ("height", c_double),
    )


def _msg(restype, argtypes, receiver, selector: str, *args):
    send = _objc().objc_msgSend
    send.restype = restype
    send.argtypes = [c_void_p, c_void_p, *argtypes]
    return send(receiver, _sel(selector), *args)


def attach_window_glass(widget: QWidget, effect: c_void_p | None) -> c_void_p | None:
    """Системное стекло на всё окно. На Windows остаётся лёгкая заливка."""
    if sys.platform != "darwin":
        return None
    app = QApplication.instance()
    if app is None or app.platformName() != "cocoa":
        return effect
    try:
        view = c_void_p(int(widget.winId()))
        window = _msg(c_void_p, [], view, "window")
        if not window:
            return effect
        _msg(None, [c_bool], window, "setOpaque:", False)
        clear = _msg(c_void_p, [], _cls("NSColor"), "clearColor")
        _msg(None, [c_void_p], window, "setBackgroundColor:", clear)
        _msg(None, [c_bool], window, "setHasShadow:", True)
        _msg(None, [c_bool], view, "setWantsLayer:", True)
        layer = _msg(c_void_p, [], view, "layer")
        if layer:
            _msg(None, [c_void_p], layer, "setBackgroundColor:", _msg(c_void_p, [], clear, "CGColor"))
            _msg(None, [c_bool], layer, "setOpaque:", False)
        host = _msg(c_void_p, [], view, "superview")
        frame = _msg(_NSRect, [], view, "frame" if host else "bounds")
        if effect is None:
            made = _msg(c_void_p, [], _cls("NSVisualEffectView"), "alloc")
            effect = _msg(c_void_p, [], made, "init")
            _msg(None, [c_long], effect, "setMaterial:", _frost_material())
            _msg(None, [c_long], effect, "setBlendingMode:", 0)
            _msg(None, [c_long], effect, "setState:", 1)
            _msg(None, [c_bool], effect, "setWantsLayer:", True)
            glass_layer = _msg(c_void_p, [], effect, "layer")
            if glass_layer:
                _msg(None, [c_double], glass_layer, "setCornerRadius:", float(RADIUS))
                _msg(None, [c_bool], glass_layer, "setMasksToBounds:", True)
            parent = host or view
            _msg(
                None,
                [c_void_p, c_long, c_void_p],
                parent,
                "addSubview:positioned:relativeTo:",
                effect,
                -1,
                view if host else None,
            )
        _msg(None, [_NSRect], effect, "setFrame:", frame)
        return effect
    except (OSError, ctypes.ArgumentError, TypeError, ValueError):
        return effect


def _frost_material() -> int:
    """Матовое стекло: тёмное как у чата M.A.I.A, светлое если система светлая."""
    app = QApplication.instance()
    dark = True
    if app is not None:
        scheme = app.styleHints().colorScheme()
        dark = scheme != Qt.ColorScheme.Light
    return 13 if dark else 6


def apply_glass_font(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = app.font()
    font.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
    font.setPointSize(13)
    app.setFont(font)


class TrafficLights(QWidget):
    closeClicked = pyqtSignal()
    minimizeClicked = pyqtSignal()
    zoomClicked = pyqtSignal()

    _COLORS = (QColor(255, 95, 87), QColor(254, 188, 46), QColor(40, 200, 64))

    def __init__(self) -> None:
        super().__init__()
        self._expanded = False
        self._hover = False
        self.setFixedSize(60, 20)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        for index, center in enumerate(self._centers()):
            dx = point.x() - center.x()
            dy = point.y() - center.y()
            if dx * dx + dy * dy <= 10 * 10:
                (self.closeClicked, self.minimizeClicked, self.zoomClicked)[index].emit()
                return

    def _centers(self) -> tuple[QPointF, QPointF, QPointF]:
        return tuple(QPointF(10 + index * 20, 10) for index in range(3))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        marks = ("x", "−", "−" if self._expanded else "+")
        pen = QPen(QColor(0, 0, 0, 153), 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for center, color, mark in zip(self._centers(), self._COLORS, marks, strict=True):
            painter.setPen(QPen(QColor(0, 0, 0, 46), 0.5))
            painter.setBrush(color)
            painter.drawEllipse(QRectF(center.x() - 6, center.y() - 6, 12, 12))
            if not self._hover:
                continue
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arm = 2.45
            if mark == "x":
                painter.drawLine(QPointF(center.x() - arm, center.y() - arm), QPointF(center.x() + arm, center.y() + arm))
                painter.drawLine(QPointF(center.x() + arm, center.y() - arm), QPointF(center.x() - arm, center.y() + arm))
            elif mark == "−":
                painter.drawLine(QPointF(center.x() - arm, center.y()), QPointF(center.x() + arm, center.y()))
            else:
                painter.drawLine(QPointF(center.x() - arm, center.y()), QPointF(center.x() + arm, center.y()))
                painter.drawLine(QPointF(center.x(), center.y() - arm), QPointF(center.x(), center.y() + arm))
        painter.end()


GLOW = (
    QColor(77, 135, 255),
    QColor(156, 115, 242),
    QColor(242, 112, 176),
    QColor(250, 173, 140),
    QColor(77, 135, 255),
)


def glow_gradient(center, angle: float, alpha: int = 255) -> QConicalGradient:
    gradient = QConicalGradient(center, angle)
    last = len(GLOW) - 1
    for index, color in enumerate(GLOW):
        faded = QColor(color)
        faded.setAlpha(alpha)
        gradient.setColorAt(index / last, faded)
    return gradient


class NetworkMark(QWidget):
    """«В сети» и огонёк: красный, пока серверов нет, зелёный, когда нашлись."""

    def __init__(self) -> None:
        super().__init__()
        self._online = False
        self._font = QFont(self.font())
        self._font.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.Medium)
        text = QFontMetrics(self._font).horizontalAdvance(tr("В сети"))
        self.setFixedSize(text + 18, 18)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_online(self, online: bool) -> None:
        self._online = bool(online)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        color = QColor(40, 200, 64) if self._online else QColor(255, 95, 87)
        halo = QColor(color)
        halo.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(0, 3, 12, 12))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(2.5, 5.5, 7, 7))
        painter.setPen(QColor(255, 255, 255, 158))
        painter.setFont(self._font)
        painter.drawText(QRectF(16, 0, self.width() - 16, self.height()), Qt.AlignmentFlag.AlignVCenter, tr("В сети"))
        painter.end()


class Wordmark(QWidget):
    """HYPERION капсом и capture надстрочно, без роста шапки."""

    def __init__(self) -> None:
        super().__init__()
        self._phase = 0.0
        self._font = QFont(self.font())
        self._font.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
        self._font.setPixelSize(16)
        self._font.setWeight(QFont.Weight.DemiBold)
        self._small = QFont(self._font)
        self._small.setPixelSize(9)
        self._small.setWeight(QFont.Weight.Medium)
        title = QFontMetrics(self._font)
        note = QFontMetrics(self._small)
        self.setFixedSize(title.horizontalAdvance("HYPERION") + 4 + note.horizontalAdvance("capture"), title.height())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_phase(self, phase: float) -> None:
        self._phase = phase
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        title = QFontMetrics(self._font)
        note = QFontMetrics(self._small)
        path = QPainterPath()
        path.addText(0, title.ascent(), self._font, "HYPERION")
        path.addText(title.horizontalAdvance("HYPERION") + 4, note.ascent(), self._small, "capture")
        painter.fillPath(path, QBrush(glow_gradient(path.boundingRect().center(), self._phase)))
        painter.end()


class GlowOverlay(QWidget):
    """Радужное кольцо M.A.I.A вокруг поля в фокусе и кнопки под курсором."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def set_phase(self, phase: float) -> None:
        self._phase = phase
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        window = self.window()
        if window is None:
            painter.end()
            return
        for widget, radius in self._targets(window):
            if not widget.isVisible():
                continue
            origin = widget.mapTo(self, QPoint(0, 0))
            rect = QRectF(origin.x() - 2, origin.y() - 2, widget.width() + 4, widget.height() + 4)
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in ((9, 70), (5, 120), (1.6, 255)):
                painter.setPen(QPen(QBrush(glow_gradient(rect.center(), self._phase, alpha)), width))
                painter.drawPath(path)
        painter.end()

    def _targets(self, window: QWidget) -> list[tuple[QWidget, float]]:
        found: list[tuple[QWidget, float]] = []
        for field in window.findChildren((QLineEdit, QSpinBox, QComboBox)):
            if not field.hasFocus():
                continue
            shell = field.parentWidget()
            target = shell if shell is not None and shell.objectName() == "inputShell" else field
            found.append((target, 16))
        for button in window.findChildren(QPushButton):
            if button.objectName() == "composer" and (button.underMouse() or button.hasFocus()):
                found.append((button, 26))
        return found


class GlassWindow(QWidget):
    """Компактное стекло у нижнего правого угла, как окно чата."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Hyperion")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(340 + SHADOW * 2, 480 + SHADOW * 2)
        self._expanded = False
        self._placed = False
        self._drag: QPoint | None = None
        self._drag_origin = QPoint()
        self.lights = TrafficLights()
        self.lights.closeClicked.connect(self.close)
        self.lights.minimizeClicked.connect(self.showMinimized)
        self.lights.zoomClicked.connect(self.toggle_expanded)
        self.wordmark = Wordmark()
        self.network = NetworkMark()
        self.glow = GlowOverlay(self)
        self.setStyleSheet(GLASS_STYLE)
        self.setAutoFillBackground(False)
        self._anim = None
        self._effect: c_void_p | None = None
        self._phase = 0.0
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(32)
        self.setMouseTracking(True)

    def toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.lights.set_expanded(self._expanded)
        self._animate(self._frame(self._expanded))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if sys.platform == "win32":
            from PyQt6.QtGui import QPainterPath, QRegion

            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), RADIUS, RADIUS)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self._effect = attach_window_glass(self, self._effect)
        self.glow.setGeometry(self.rect())
        self.glow.raise_()

    def _tick(self) -> None:
        self._phase = (self._phase + 2.56) % 360
        self.wordmark.set_phase(self._phase)
        self.glow.set_phase(self._phase)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        veil = 28 if self._effect is not None else 168
        painter.setBrush(QColor(18, 20, 24, veil))
        painter.drawRoundedRect(bounds, RADIUS, RADIUS)
        painter.setPen(QPen(QBrush(glow_gradient(QPointF(bounds.center()), self._phase)), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bounds, RADIUS, RADIUS)
        painter.end()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._effect = attach_window_glass(self, self._effect)
        self.glow.setGeometry(self.rect())
        self.glow.raise_()
        if self._placed:
            return
        screen = self.screen()
        if screen is None:
            return
        self._placed = True
        self.setGeometry(self._frame(False))

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_header(event.position().toPoint()):
            self.toggle_expanded()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_header(event.position().toPoint()):
            self._drag = event.globalPosition().toPoint()
            self._drag_origin = self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(self._drag_origin + event.globalPosition().toPoint() - self._drag)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        super().mouseReleaseEvent(event)

    def _on_header(self, point: QPoint) -> bool:
        parent = self.lights.parentWidget()
        if parent is not None and self.lights.geometry().contains(parent.mapFrom(self, point)):
            return False
        header_bottom = SHADOW + 46
        return SHADOW <= point.y() <= header_bottom

    def _frame(self, expanded: bool) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        width, height = EXPANDED if expanded else COMPACT
        width = min(width, area.width() - 32)
        height = min(height, area.height() - 32)
        outer_w = width + SHADOW * 2
        outer_h = height + SHADOW * 2
        if expanded:
            x = area.x() + (area.width() - outer_w) // 2
            y = area.y() + (area.height() - outer_h) // 2
        else:
            x = area.right() - 16 - outer_w + SHADOW
            y = area.bottom() - 16 - outer_h + SHADOW
        return QRect(int(x), int(y), int(outer_w), int(outer_h))

    def _animate(self, target: QRect) -> None:
        from PyQt6.QtCore import QPropertyAnimation

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(280)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self.geometry())
        anim.setEndValue(target)
        anim.start()
        self._anim = anim

    def header_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setObjectName("glassBody")
        layout = QGridLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.addWidget(self.wordmark, 0, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lights, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.network, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return bar
