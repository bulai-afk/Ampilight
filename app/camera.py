"""Камера ноутбука. Кадры приходят как RGB uint8."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import (
    QCamera,
    QCameraDevice,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoFrame,
    QVideoSink,
)


def laptop_camera() -> QCameraDevice | None:
    """Встроенная камера, без камеры iPhone."""
    fallback = None
    for device in QMediaDevices.videoInputs():
        if device.isNull():
            continue
        name = device.description().casefold()
        if "facetime" in name or "face time" in name:
            return device
        if "iphone" in name or "ipad" in name:
            continue
        if fallback is None:
            fallback = device
    return fallback


def _choose_format(device: QCameraDevice):
    best = None
    best_rank = None
    for fmt in device.videoFormats():
        size = fmt.resolution()
        width = size.width()
        height = size.height()
        if width < 320 or height < 240 or width > 960:
            continue
        fps = fmt.maxFrameRate()
        if fps < 10:
            continue
        rank = (abs(width - 640), abs(height - 480), -min(fps, 30))
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = fmt
    return best


def frame_to_rgb(frame: QVideoFrame) -> np.ndarray | None:
    if not frame.isValid():
        return None
    image = frame.toImage()
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    width = image.width()
    height = image.height()
    if width < 16 or height < 16:
        return None
    stride = image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(height * stride)
    raw = np.frombuffer(pointer, dtype=np.uint8).reshape((height, stride))
    return raw[:, : width * 3].reshape((height, width, 3)).copy()


class LaptopCamera(QObject):
    rgb = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.device_name = ""
        self._camera: QCamera | None = None
        self._session: QMediaCaptureSession | None = None
        self._sink = QVideoSink()
        self._sink.videoFrameChanged.connect(self._on_video)

    def running(self) -> bool:
        return self._camera is not None

    def start(self) -> str:
        self.stop()
        device = laptop_camera()
        if device is None:
            return "Камера ноутбука не найдена."
        self.device_name = device.description()
        camera = QCamera(device)
        fmt = _choose_format(device)
        if fmt is not None:
            camera.setCameraFormat(fmt)
        session = QMediaCaptureSession()
        session.setCamera(camera)
        session.setVideoSink(self._sink)
        camera.errorOccurred.connect(self._on_error)
        camera.activeChanged.connect(self._relax)
        self._camera = camera
        self._session = session
        camera.start()
        return ""

    def _relax(self, active: bool) -> None:
        """Меньше света и без фокуса на лицо, иначе чёрный синеет, а серый белеет."""
        camera = self._camera
        if not active or camera is None:
            return
        if camera.supportedFeatures().value & QCamera.Feature.ExposureCompensation.value:
            camera.setExposureCompensation(-1.0)
        if camera.isFocusModeSupported(QCamera.FocusMode.FocusModeInfinity):
            camera.setFocusMode(QCamera.FocusMode.FocusModeInfinity)

    def stop(self) -> None:
        camera = self._camera
        self._camera = None
        self._session = None
        if camera is not None:
            camera.stop()

    def _on_video(self, frame: QVideoFrame) -> None:
        rgb = frame_to_rgb(frame)
        if rgb is not None:
            self.rgb.emit(rgb)

    def _on_error(self, _error, message: str) -> None:
        text = message.casefold()
        if any(word in text for word in ("author", "permission", "denied", "доступ")):
            self.failed.emit(
                "Нет доступа к камере. Системные настройки → "
                "Конфиденциальность и безопасность → Камера → включи Cursor."
            )
            return
        if message:
            self.failed.emit(f"Камера: {message}")
