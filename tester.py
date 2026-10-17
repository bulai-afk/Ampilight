#!/usr/bin/env python3
"""Простой тест ленты: выбрать плату, способ связи, устройство и погонять красный огонёк.

    python3 tester.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import serial
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.sender import FindThread, LanSender, list_serial_ports

UDP_PORT = 4210
STEP_MS = 80
# Полный красный на 90 диодах тянет около 1,8 А — больше, чем даёт USB-порт Mac.
ALL_RED_LEVEL = 96
CHASE_TEXT = "Тест: красный огонёк"
ALL_TEXT = "Тест: всё красным"


class Switch(QAbstractButton):
    """Двухпозиционный переключатель: выключен — USB, включён — Wi-Fi."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(46, 24)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        on = self.isChecked()
        if not self.isEnabled():
            track = QColor("#bbbbbb")
        else:
            track = QColor("#2f80ed") if on else QColor("#8a8a8a")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        knob = rect.height() - 4
        x = rect.right() - knob - 2 if on else rect.left() + 2
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(x, rect.top() + 2, knob, knob))


class Link:
    """Отправка пакета 'D' + RGB по UDP или по USB."""

    def __init__(self, mode: str, target: str) -> None:
        self.mode = mode
        self.target = target
        self._lan = LanSender()
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        if self.mode == "wifi":
            return
        ser = serial.Serial()
        ser.port = self.target
        ser.baudrate = 115200
        ser.timeout = 0
        ser.write_timeout = 0.25
        # Без DTR/RTS плата не перезагружается при открытии порта.
        ser.dtr = False
        ser.rts = False
        ser.open()
        self._ser = ser

    def send(self, packet: bytes) -> None:
        if self.mode == "wifi":
            self._lan.send(self.target, UDP_PORT, packet)
            return
        if self._ser is not None:
            self._ser.write(packet)

    def close(self) -> None:
        self._lan.close()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None


def frame(count: int, lit: int | None) -> bytes:
    data = bytearray(b"D")
    data.extend(b"\x00" * (count * 3))
    if lit is not None:
        data[1 + lit * 3] = 255
    return bytes(data)


def all_red(count: int) -> bytes:
    return b"D" + bytes((ALL_RED_LEVEL, 0, 0)) * count


class TestWindow(QDialog):
    def __init__(self, link: Link, leds: int, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Тест ленты")
        self.setMinimumWidth(320)
        self._link = link
        self._leds = leds
        self._index = 0
        self._mode: str | None = None

        self.info = QLabel(f"{title}\nДиодов: {leds}")
        self.chase_button = self._mode_button(CHASE_TEXT, "chase")
        self.all_button = self._mode_button(ALL_TEXT, "all")
        self.status = QLabel("Выбери тест.")
        self.status.setWordWrap(True)
        close_button = QPushButton("Отключиться")
        close_button.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.chase_button)
        layout.addWidget(self.all_button)
        layout.addWidget(self.status)
        layout.addWidget(close_button)

        self._timer = QTimer(self)
        self._timer.setInterval(STEP_MS)
        self._timer.timeout.connect(self._step)

    def _mode_button(self, text: str, mode: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setMinimumHeight(44)
        button.toggled.connect(lambda on: self._toggle(mode, on))
        return button

    def _send(self, packet: bytes) -> bool:
        try:
            self._link.send(packet)
        except Exception as exc:
            self.status.setText(f"Ошибка отправки: {exc}")
            self._set_mode(None)
            return False
        return True

    def _set_mode(self, mode: str | None) -> None:
        self._mode = mode
        for button, name, text in (
            (self.chase_button, "chase", CHASE_TEXT),
            (self.all_button, "all", ALL_TEXT),
        ):
            button.blockSignals(True)
            button.setChecked(name == mode)
            button.setText("Стоп" if name == mode else text)
            button.blockSignals(False)
        if mode is None:
            self._timer.stop()
            self._send(frame(self._leds, None))
            return
        self._index = 0
        self._timer.start()
        self._step()

    def _toggle(self, mode: str, on: bool) -> None:
        self._set_mode(mode if on else None)

    def _step(self) -> None:
        if self._mode == "all":
            # Пакет шлётся повторно: по Wi-Fi одиночный UDP-пакет может потеряться.
            if self._send(all_red(self._leds)):
                self.status.setText(
                    f"Все {self._leds} диодов красные. Если лента мерцает или плата "
                    "перезагружается — не хватает тока от USB."
                )
        elif self._mode == "chase":
            if self._send(frame(self._leds, self._index)):
                self.status.setText(f"Горит диод {self._index + 1} из {self._leds}")
                self._index = (self._index + 1) % self._leds

    def closeEvent(self, event) -> None:
        self._timer.stop()
        try:
            self._link.send(frame(self._leds, None))
        except Exception:
            pass
        self._link.close()
        super().closeEvent(event)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ampilight — подключение")
        self.setMinimumWidth(380)
        self._finder: FindThread | None = None

        self.board = QComboBox()
        self.board.addItem("ESP32", "esp32")
        self.board.addItem("Arduino Nano", "nano")
        self.board.currentIndexChanged.connect(self._board_changed)

        self.switch = Switch()
        self.switch.setChecked(True)
        self.switch.toggled.connect(self._refresh)
        self.usb_label = QLabel("USB")
        self.wifi_label = QLabel("Wi-Fi")
        link_row = QHBoxLayout()
        link_row.addWidget(self.usb_label)
        link_row.addWidget(self.switch)
        link_row.addWidget(self.wifi_label)
        link_row.addStretch(1)

        self.device = QComboBox()
        self.device.setMinimumWidth(220)
        self.device.currentIndexChanged.connect(self._device_changed)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self._refresh)
        device_row = QHBoxLayout()
        device_row.addWidget(self.device, 1)
        device_row.addWidget(refresh)

        self.leds = QSpinBox()
        self.leds.setRange(1, 512)
        self.leds.setValue(90)
        self.leds_label = QLabel("Диодов")

        form = QFormLayout()
        form.addRow("Плата", self.board)
        form.addRow("Связь", link_row)
        form.addRow("Устройство", device_row)
        form.addRow(self.leds_label, self.leds)

        self.connect_button = QPushButton("Подключиться")
        self.connect_button.setMinimumHeight(40)
        self.connect_button.clicked.connect(self._connect)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.connect_button)
        layout.addWidget(self.status)

        self._refresh()

    def _wifi(self) -> bool:
        return self.switch.isChecked() and self.switch.isEnabled()

    def _board_changed(self) -> None:
        nano = self.board.currentData() == "nano"
        self.switch.setEnabled(not nano)
        self.wifi_label.setEnabled(not nano)
        self._refresh()

    def _refresh(self) -> None:
        self.device.clear()
        self.connect_button.setEnabled(False)
        self.usb_label.setStyleSheet("" if self._wifi() else "font-weight: bold")
        self.wifi_label.setStyleSheet("font-weight: bold" if self._wifi() else "")
        if self._wifi():
            if self._finder is not None and self._finder.isRunning():
                return
            self.status.setText("Ищу платы в Wi-Fi сети…")
            self._finder = FindThread(UDP_PORT)
            self._finder.found.connect(self._found)
            self._finder.start()
            return
        usb_marks = ("usb", "wch", "slab")
        ports = [port for port in list_serial_ports() if any(mark in port.lower() for mark in usb_marks)]
        for port in ports:
            self.device.addItem(port, port)
        if ports:
            self.status.setText("Выбери USB-порт платы.")
        else:
            self.status.setText("USB-устройств нет. Проверь кабель и нажми «Обновить».")
        self._device_changed()

    def _found(self, result) -> None:
        if not self._wifi():
            return
        self.device.clear()
        if isinstance(result, Exception):
            self.status.setText(f"Поиск не удался: {result}")
            return
        for host, leds in result:
            self.device.addItem(f"{host} — {leds} диодов", (host, leds))
        if result:
            self.status.setText(f"Найдено плат: {len(result)}")
        else:
            self.status.setText(
                "В сети плат нет. Плата должна быть прошита и в той же сети, что и Mac. "
                "Нажми «Обновить», чтобы искать ещё раз."
            )
        self._device_changed()

    def _device_changed(self) -> None:
        data = self.device.currentData()
        self.connect_button.setEnabled(data is not None)
        usb = not self._wifi()
        self.leds.setVisible(usb)
        self.leds_label.setVisible(usb)

    def _connect(self) -> None:
        data = self.device.currentData()
        if data is None:
            return
        if self._wifi():
            host, leds = data
            link = Link("wifi", host)
            title = f"{self.board.currentText()} по Wi-Fi: {host}"
        else:
            link = Link("usb", data)
            leds = self.leds.value()
            title = f"{self.board.currentText()} по USB: {data}"
        if leds < 1:
            self.status.setText("Плата не сообщила число диодов.")
            return
        try:
            link.open()
        except Exception as exc:
            self.status.setText(f"Не подключился: {exc}")
            return
        if link.mode == "usb":
            self.status.setText("Порт открыт, жду плату…")
            QApplication.processEvents()
            time.sleep(1.5)
        self.status.setText("")
        TestWindow(link, leds, title, self).exec()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
