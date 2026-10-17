"""Кадры с Android-ТВ через adb: на ТВ крутится app/tvgrab.dex и шлёт сырые RGBA."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

DEX = Path(__file__).with_name("tvgrab.dex")
REMOTE_DEX = "/data/local/tmp/tvgrab.dex"
MAGIC = b"AMPF"
# Точек снимка на один диод. Меньше нельзя: ТВ при сильном сжатии берёт пару точек
# вместо среднего, и цвет диода начинает прыгать от мелких деталей.
POINTS_PER_LED = 4


def grab_size(top: int, bottom: int, left: int, right: int) -> tuple[int, int]:
    width = max(16, max(top, bottom, 1) * POINTS_PER_LED)
    height = max(9, max(left, right, 1) * POINTS_PER_LED)
    return width + (width & 1), height + (height & 1)


def adb_path() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    fallback = Path.home() / "Library/Android/sdk/platform-tools/adb"
    return str(fallback) if fallback.is_file() else None


def _run(adb: str, *args: str, timeout: float = 10) -> str:
    done = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout)
    return (done.stdout or "") + (done.stderr or "")


def find_tv(adb: str) -> str:
    """Серийник ТВ в adb. Если в списке пусто — ищем ТВ через mDNS и подключаемся."""

    def ready() -> list[str]:
        lines = _run(adb, "devices").splitlines()[1:]
        return [line.split()[0] for line in lines if line.strip().endswith("device")]

    serials = ready()
    if serials:
        return serials[0]
    for line in _run(adb, "mdns", "services").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("_adb._tcp"):
            _run(adb, "connect", parts[2])
    serials = ready()
    return serials[0] if serials else ""


class TvStream(QObject):
    rgb = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.serial = ""
        self.width = 0
        self.height = 0
        self.fps = 0
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, width: int, height: int, fps: int) -> None:
        self.stop()
        self.width = width
        self.height = height
        self.fps = fps
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ampilight-tv", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.kill()
            self._kill_remote()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _kill_remote(self) -> None:
        """Снимки на ТВ тормозят видео, поэтому процесс там нельзя оставлять."""
        adb = adb_path()
        if adb and self.serial:
            try:
                _run(adb, "-s", self.serial, "shell", "pkill -f 'app_process / Grab'", timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass

    def _loop(self) -> None:
        adb = adb_path()
        if adb is None:
            self.failed.emit("Не найден adb. Поставь Android Studio или brew install android-platform-tools.")
            return
        try:
            self.serial = find_tv(adb)
            if not self.serial:
                self.failed.emit(
                    "Телевизор не найден. Включи на нём «Отладка по USB» в разделе «Для разработчиков»."
                )
                return
            pushed = _run(adb, "-s", self.serial, "push", str(DEX), REMOTE_DEX, timeout=20)
            if "error" in pushed.casefold() or "unauthorized" in pushed.casefold():
                self.failed.emit("Телевизор не пускает: разреши отладку на экране ТВ.")
                return
            self._kill_remote()
        except (OSError, subprocess.SubprocessError) as exc:
            self.failed.emit(f"adb: {exc}")
            return
        width, height = self.width, self.height
        command = f"CLASSPATH={REMOTE_DEX} nice -n 19 app_process / Grab {width} {height} {self.fps}"
        process = subprocess.Popen(
            [adb, "-s", self.serial, "exec-out", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._process = process
        size = width * height * 4
        buffer = b""
        while not self._stop.is_set():
            chunk = process.stdout.read1(1 << 16) if process.stdout else b""
            if not chunk:
                if not self._stop.is_set():
                    self.failed.emit("Связь с телевизором оборвалась.")
                return
            buffer += chunk
            while True:
                start = buffer.find(MAGIC)
                if start < 0:
                    buffer = buffer[-3:]
                    break
                end = start + 8 + size
                if len(buffer) < end:
                    buffer = buffer[start:]
                    break
                raw = np.frombuffer(buffer, dtype=np.uint8, count=size, offset=start + 8)
                frame = raw.reshape((height, width, 4))[:, :, :3].copy()
                buffer = buffer[end:]
                self.rgb.emit(frame)
