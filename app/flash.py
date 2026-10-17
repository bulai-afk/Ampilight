"""Сборка и прошивка Nano / ESP32 через arduino-cli."""

from __future__ import annotations

import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ModuleNotFoundError:
    QThread = object
    pyqtSignal = None

ROOT = Path(__file__).resolve().parents[1]

BOARDS = {
    "nano-old": {
        "fqbn": "arduino:avr:nano:cpu=atmega328old",
        "core": "arduino:avr",
        "sketch": "ambilight_nano",
        "template": ROOT / "firmware" / "arduino_nano" / "ambilight_nano.ino",
        "wifi": False,
    },
    "nano": {
        "fqbn": "arduino:avr:nano:cpu=atmega328",
        "core": "arduino:avr",
        "sketch": "ambilight_nano",
        "template": ROOT / "firmware" / "arduino_nano" / "ambilight_nano.ino",
        "wifi": False,
    },
    "esp32": {
        "fqbn": "esp32:esp32:esp32:UploadSpeed=460800",
        "core": "esp32:esp32@2.0.17",
        "sketch": "ambilight_esp32",
        "template": ROOT / "firmware" / "esp32_wifi" / "ambilight_esp32.ino",
        "wifi": True,
    },
}

ORDERS = {"GRB": "NEO_GRB", "RGB": "NEO_RGB"}


def arduino_cli() -> str | None:
    found = shutil.which("arduino-cli")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/arduino-cli", "/usr/local/bin/arduino-cli"):
        if Path(candidate).is_file():
            return candidate
    return None


def c_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def write_sketch(
    board_id: str,
    leds: int,
    pin: int,
    order: str,
    ssid: str,
    password: str,
    udp_port: int,
) -> Path:
    board = BOARDS[board_id]
    dest = ROOT / "build" / board["sketch"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copy(board["template"], dest / f"{board['sketch']}.ino")
    lines = [
        "#pragma once",
        f"#define AMP_NUM_LEDS {int(leds)}",
        f"#define AMP_DATA_PIN {int(pin)}",
        f"#define AMP_ORDER {ORDERS.get(order, 'NEO_GRB')}",
        f'#define AMP_WIFI_SSID "{c_escape(ssid)}"',
        f'#define AMP_WIFI_PASS "{c_escape(password)}"',
        f"#define AMP_UDP_PORT {int(udp_port)}",
        "",
    ]
    (dest / "config.h").write_text("\n".join(lines), encoding="utf-8")
    return dest


def _is_ip(port: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", port))


def _espota() -> Path:
    root = Path.home() / "Library/Arduino15/packages/esp32/hardware/esp32"
    found = sorted(root.glob("*/tools/espota.py"))
    if not found:
        raise RuntimeError("Не найден espota.py. Ядро ESP32 должно быть установлено.")
    return found[-1]


def _shown(args: list[str]) -> str:
    hidden = []
    for arg in args:
        if arg.startswith("--auth="):
            hidden.append("--auth=***")
        else:
            hidden.append(arg)
    return " ".join(hidden)


def _esptool() -> Path:
    root = Path.home() / "Library/Arduino15/packages/esp32/tools/esptool_py"
    found = sorted(path for path in root.glob("*/esptool") if path.is_file())
    if not found:
        raise RuntimeError("Не найден esptool. Ядро ESP32 должно быть установлено.")
    return found[-1]


def _boot_app0() -> Path:
    root = Path.home() / "Library/Arduino15/packages/esp32/hardware/esp32"
    found = sorted(root.glob("*/tools/partitions/boot_app0.bin"))
    if not found:
        raise RuntimeError("Не найден boot_app0.bin. Ядро ESP32 должно быть установлено.")
    return found[-1]


def _friendly(text: str) -> str:
    low = text.lower()
    compact = text.strip()
    if len(compact) > 700:
        compact = compact[-700:]
    if "writing at" in low or "hash of data verified" in low:
        return compact or "Запись оборвалась"
    if any(token in low for token in ("failed to connect", "no serial data", "packet header", "timed out waiting")):
        return (
            "Плата не вошла в режим прошивки. Зажми кнопку BOOT на ESP32, "
            "нажми «Прошить» ещё раз и отпусти BOOT, когда в журнале появится Writing."
        )
    return compact or "Прошивка остановилась с ошибкой"


def _run(cli: str, args: list[str], log, timeout: float | None = None, echo: bool = True) -> None:
    cmd = [cli, *args]
    if echo:
        log("$ " + _shown(args))
    master, slave = pty.openpty()
    proc = subprocess.Popen(cmd, stdout=slave, stderr=slave, stdin=subprocess.DEVNULL, close_fds=True)
    os.close(slave)
    start = time.monotonic()
    pending = ""
    captured: list[str] = []

    def take(force: bool = False) -> None:
        nonlocal pending
        parts = re.split(r"[\r\n]", pending)
        pending = "" if force else parts[-1]
        body = parts if force else parts[:-1]
        for part in body:
            line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", part).strip()
            if not line:
                continue
            captured.append(line)
            log(line[:240])

    try:
        while True:
            if timeout is not None and time.monotonic() - start > timeout:
                proc.kill()
                proc.wait(timeout=5)
                raise RuntimeError(
                    "Прошивка слишком долго ждёт плату. Зажми кнопку BOOT, нажми «Прошить» "
                    "ещё раз и отпусти BOOT, когда в журнале появится Writing."
                )
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                try:
                    data = os.read(master, 1024)
                except OSError:
                    data = b""
                if data:
                    pending += data.decode("utf-8", errors="replace")
                    take()
                    continue
            if proc.poll() is not None:
                try:
                    while True:
                        extra = os.read(master, 4096)
                        if not extra:
                            break
                        pending += extra.decode("utf-8", errors="replace")
                except OSError:
                    pass
                take(force=True)
                break
    finally:
        os.close(master)
    code = proc.wait(timeout=5)
    if code != 0:
        raise RuntimeError(_friendly("\n".join(captured[-12:])))


def _core_installed(cli: str, core_id: str) -> bool:
    name, _, version = core_id.partition("@")
    proc = subprocess.run([cli, "core", "list"], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts or parts[0] != name:
            continue
        if not version or (len(parts) > 1 and parts[1] == version):
            return True
    return False


def flash_board(
    *,
    board_id: str,
    port: str,
    leds: int,
    pin: int,
    order: str,
    ssid: str,
    password: str,
    udp_port: int,
    ota_auth: str = "",
    log,
) -> None:
    cli = arduino_cli()
    if cli is None:
        raise RuntimeError("arduino-cli не найден. Поставь его командой brew install arduino-cli")
    if board_id not in BOARDS:
        raise RuntimeError("Неизвестная плата")
    over_wifi = _is_ip(port)
    if not port:
        raise RuntimeError("Нет USB и плата не найдена в Wi-Fi")
    if leds < 1 or leds > 512:
        raise RuntimeError("Число диодов должно быть от 1 до 512")
    board = BOARDS[board_id]
    if not board["wifi"] and leds > 180:
        raise RuntimeError(
            "На Arduino Nano не больше 180 диодов — не хватит памяти. Для длинной ленты прошивай ESP32."
        )
    if board["wifi"] and not ssid.strip():
        raise RuntimeError("Для ESP32 нужно имя Wi-Fi")
    sketch = write_sketch(board_id, leds, pin, order, ssid, password, udp_port)
    if not _core_installed(cli, board["core"]):
        log(f"Скачиваю ядро {board['core']}. Для ESP32 это занимает несколько минут.")
        _run(cli, ["core", "update-index"], log)
        _run(cli, ["core", "install", board["core"]], log)
    listed = subprocess.run([cli, "lib", "list"], capture_output=True, text=True)
    if "NeoPixel" not in listed.stdout:
        try:
            _run(cli, ["lib", "install", "Adafruit NeoPixel"], log)
        except RuntimeError as exc:
            if "multiple installations" not in str(exc):
                raise
    build_path = ROOT / "build" / "firmware-out"
    if build_path.exists():
        shutil.rmtree(build_path)
    _run(
        cli,
        ["compile", "--fqbn", board["fqbn"], "--build-path", str(build_path), str(sketch)],
        log,
    )
    if over_wifi:
        binary = build_path / f"{board['sketch']}.ino.bin"
        if not binary.is_file():
            raise RuntimeError("Сборка не создала файл прошивки")
        log(f"Отправляю прошивку по Wi-Fi на {port}")
        _run(
            sys.executable,
            [
                str(_espota()),
                "-r",
                "-i",
                port,
                "-p",
                "3232",
                f"--auth={ota_auth or password}",
                "-f",
                str(binary),
            ],
            log,
        )
        return
    if board_id == "esp32":
        _upload_esp32_usb(port, build_path, board["sketch"], log)
        return
    _run(cli, ["upload", "-p", port, "--fqbn", board["fqbn"], "--input-dir", str(build_path), str(sketch)], log)


def _upload_esp32_usb(port: str, build_path: Path, sketch_name: str, log) -> None:
    app = build_path / f"{sketch_name}.ino.bin"
    bootloader = next(build_path.glob(f"{sketch_name}.ino.bootloader.bin"), None)
    partitions = next(build_path.glob(f"{sketch_name}.ino.partitions.bin"), None)
    if not app.is_file() or bootloader is None or partitions is None:
        raise RuntimeError("Сборка не создала файлы прошивки")
    log("Сборка готова. Соединяюсь с платой — обычно это секунд пятнадцать, потом пойдёт Writing.")
    _run(
        str(_esptool()),
        [
            "--chip",
            "esp32",
            "--port",
            port,
            "--baud",
            "460800",
            "--before",
            "default_reset",
            "--after",
            "hard_reset",
            "--connect-attempts",
            "8",
            "write_flash",
            "-z",
            "--flash_mode",
            "dio",
            "--flash_freq",
            "80m",
            "--flash_size",
            "4MB",
            "0x1000",
            str(bootloader),
            "0x8000",
            str(partitions),
            "0xe000",
            str(_boot_app0()),
            "0x10000",
            str(app),
        ],
        log,
        timeout=180,
        echo=False,
    )


class FlashJob(QThread):
    if pyqtSignal is not None:
        line = pyqtSignal(str)
        done = pyqtSignal(bool, str)

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            flash_board(log=self.line.emit, **self._kwargs)
        except Exception as exc:
            self.line.emit(str(exc))
            self.done.emit(False, str(exc))
            return
        self.done.emit(True, "Прошивка записана")
