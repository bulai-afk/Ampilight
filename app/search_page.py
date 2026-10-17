"""Экран поиска: иконка сервера, огоньки и список найденных."""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.discover import ServerSearch, lan_access_denied
from app.glass import glow_gradient
from app.i18n import tr

_SPARKS = (
    QColor(77, 135, 255),
    QColor(156, 115, 242),
    QColor(242, 112, 176),
    QColor(250, 173, 140),
)


class _Spark:
    def __init__(self, x: float, y: float) -> None:
        angle = random.random() * math.tau
        speed = random.uniform(0.7, 2.4)
        self.x = x
        self.y = y
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = random.uniform(0.55, 1.0)
        self.radius = random.uniform(1.6, 3.2)
        self.color = random.choice(_SPARKS)

    def step(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.life -= 0.012
        return self.life > 0


class ServerBeacon(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(220)
        self._sparks: list[_Spark] = []
        self._phase = 0.0
        self._searching = True
        self._caption = tr("Ищем Hyperion…")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self) -> None:
        self._phase = (self._phase + 1.28) % 360
        origin = self._origin()
        if self.width() > 40 and random.random() < 0.72 and len(self._sparks) < 48:
            self._sparks.append(_Spark(origin.x(), origin.y()))
        self._sparks = [spark for spark in self._sparks if spark.step()]
        self.update()

    def set_searching(self, searching: bool) -> None:
        self._searching = searching
        self.update()

    def set_caption(self, text: str) -> None:
        self._caption = text
        self._searching = True
        self.update()

    def _origin(self) -> QPointF:
        """Иконка и подпись — одна группа по центру окна."""
        x = self.width() / 2
        y = self.height() / 2 - 12
        window = self.window()
        if window is not None:
            top = self.mapTo(window, QPoint(0, 0)).y()
            y = window.height() / 2 - top - 12
        low = 48.0
        high = max(low, self.height() - 72)
        return QPointF(x, min(max(y, low), high))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        origin = self._origin()
        for spark in self._sparks:
            color = QColor(spark.color)
            color.setAlpha(int(180 * spark.life))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(spark.x, spark.y), spark.radius * 2.4, spark.radius * 2.4)
            color.setAlpha(int(255 * spark.life))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(spark.x, spark.y), spark.radius, spark.radius)
        self._draw_server(painter, origin)
        self._draw_caption(painter, origin)
        painter.end()

    def _draw_server(self, painter: QPainter, origin: QPointF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        body = QRectF(origin.x() - 28, origin.y() - 34, 56, 68)
        painter.setBrush(QColor(245, 245, 247, 235))
        painter.drawRoundedRect(body, 12, 12)
        for index in range(3):
            slot = QRectF(body.left() + 10, body.top() + 12 + index * 16, body.width() - 20, 8)
            painter.setBrush(QColor(13, 30, 53, 200))
            painter.drawRoundedRect(slot, 3, 3)
            led = QColor(120, 230, 150) if index == 0 else QColor(77, 135, 255)
            painter.setBrush(led)
            painter.drawEllipse(QPointF(slot.right() - 6, slot.center().y()), 2.2, 2.2)
        painter.setPen(QPen(QBrush(glow_gradient(body.center(), self._phase)), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body.adjusted(0.8, 0.8, -0.8, -0.8), 11, 11)

    def _draw_caption(self, painter: QPainter, origin: QPointF) -> None:
        if not self._searching:
            return
        font = QFont(self.font())
        font.setFamilies([".AppleSystemUIFont", "SF Pro Text", "Helvetica Neue", "Segoe UI"])
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        text = self._caption
        metrics = QFontMetrics(font)
        x = origin.x() - metrics.horizontalAdvance(text) / 2
        path = QPainterPath()
        path.addText(x, origin.y() + 56, font, text)
        rect = path.boundingRect()
        painter.fillPath(path, QColor(255, 255, 255, 158))
        painter.save()
        painter.setClipPath(path)
        painter.setOpacity(0.55)
        painter.fillPath(path, QBrush(glow_gradient(rect.center(), self._phase)))
        painter.restore()


class _ServerMark(QWidget):
    """Маленькая иконка сервера на карточке."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(28, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        body = QRectF(3, 2, 22, 30)
        painter.setBrush(QColor(13, 30, 53))
        painter.drawRoundedRect(body, 5, 5)
        for index in range(3):
            slot = QRectF(body.left() + 3, body.top() + 5 + index * 8, body.width() - 6, 4.5)
            painter.setBrush(QColor(245, 245, 247))
            painter.drawRoundedRect(slot, 1.6, 1.6)
            painter.setBrush(QColor(120, 230, 150) if index == 0 else QColor(77, 135, 255))
            painter.drawEllipse(QPointF(slot.right() - 2.4, slot.center().y()), 1.15, 1.15)
        painter.end()


class _NetMark(QWidget):
    """Маленький значок сети у адреса."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(13, 13)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(13, 30, 53, 150), 1.15)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(1, 1, 11, 11))
        painter.drawEllipse(QRectF(4.1, 1, 4.8, 11))
        painter.drawLine(QPointF(1.4, 6.5), QPointF(11.6, 6.5))
        painter.end()


class _BulbCount(QWidget):
    """Лампочка и число приборов."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFixedSize(22 + QFontMetrics(font).horizontalAdvance(str(count)), 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(250, 196, 92))
        painter.drawEllipse(QRectF(1, 1, 14, 14))
        painter.setBrush(QColor(13, 30, 53))
        painter.drawRoundedRect(QRectF(5.2, 14.2, 5.6, 3.2), 1, 1)
        painter.drawRoundedRect(QRectF(4.2, 17, 7.6, 2.4), 1, 1)
        painter.setPen(QColor(13, 30, 53))
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(20, 0, self.width() - 20, 22), Qt.AlignmentFlag.AlignVCenter, str(self._count))
        painter.end()


class SearchPage(QWidget):
    chosen = pyqtSignal(str, int)
    manual = pyqtSignal()
    presence = pyqtSignal(bool)

    def __init__(self, prefer: str = "") -> None:
        super().__init__()
        self.setObjectName("page")
        self._anims: list = []
        self._rows: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 4, 24, 16)
        layout.setSpacing(8)
        self.beacon = ServerBeacon()
        layout.addWidget(self.beacon, 1)

        holder = QWidget()
        holder.setObjectName("page")
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(holder)
        self._scroll.setMinimumHeight(0)
        self._scroll.setMaximumHeight(168)
        layout.addWidget(self._scroll)

        manual = QPushButton(tr("Подключиться вручную"))
        manual.setObjectName("textButton")
        manual.setCursor(Qt.CursorShape.PointingHandCursor)
        manual.clicked.connect(self.manual.emit)
        layout.addWidget(manual, 0, Qt.AlignmentFlag.AlignHCenter)

        self._prefer = prefer
        self._search: ServerSearch | None = None

    def _start_search(self) -> None:
        self._search = ServerSearch(self._prefer)
        self._search.found.connect(self._add_server)
        self._search.scan_finished.connect(self._search_finished)
        self._search.access_denied.connect(self._access_denied)
        self._search.start()

    def retry(self) -> None:
        if self._rows or (self._search is not None and self._search.isRunning()):
            return
        self.beacon.set_caption(tr("Ищем Hyperion…"))
        self._start_search()

    def _access_denied(self) -> None:
        if not self._rows:
            self.beacon.set_caption(tr("Нажми «Разрешить» у значка глобуса"))

    def _search_finished(self) -> None:
        if self._rows:
            return
        if lan_access_denied():
            self.beacon.set_caption(tr("Нажми «Разрешить» у значка глобуса"))
        else:
            self.beacon.set_caption(tr("Сервер не найден"))

    def _follow_list(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def stop(self) -> None:
        self.beacon._timer.stop()
        if self._search is None:
            return
        self._search.stop()
        self._search.wait(1500)

    def _add_server(self, name: str, host: str, port: int, devices: int) -> None:
        if host in self._rows:
            return
        if not self._rows:
            self.beacon.set_searching(False)
            self.presence.emit(True)
        button = QPushButton()
        button.setObjectName("server")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, address=host, number=port: self.chosen.emit(address, number))
        row = QHBoxLayout(button)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)
        row.addWidget(_ServerMark(), 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        title = QLabel(name)
        title.setObjectName("serverName")
        host_line = QLabel(f"{host}:{port}")
        host_line.setObjectName("serverHost")
        for label in (title, host_line):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        address = QHBoxLayout()
        address.setContentsMargins(0, 0, 0, 0)
        address.setSpacing(5)
        address.addWidget(_NetMark(), 0, Qt.AlignmentFlag.AlignVCenter)
        address.addWidget(host_line, 1)
        text.addWidget(title)
        text.addLayout(address)
        row.addLayout(text, 1)
        row.addWidget(_BulbCount(devices), 0, Qt.AlignmentFlag.AlignVCenter)
        button.setFixedHeight(58)
        shell = QWidget()
        shell.setObjectName("page")
        box = QVBoxLayout(shell)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        box.addWidget(button)
        shell.setMaximumHeight(0)
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(0)
        button.setGraphicsEffect(effect)
        self._rows[host] = button
        self._list.addWidget(shell)
        self._scroll.setMinimumHeight(min(168, 66 * len(self._rows)))
        target = 58
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(420)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        rise = QPropertyAnimation(shell, b"maximumHeight", self)
        rise.setDuration(420)
        rise.setStartValue(0)
        rise.setEndValue(target)
        rise.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.start()
        rise.start()
        self._anims.extend((fade, rise))
        QTimer.singleShot(30, self._follow_list)
        QTimer.singleShot(430, self._follow_list)
