"""Отправка пакета 'D' + RGB на Arduino по USB и на ESP32 по UDP."""

from __future__ import annotations

import errno
import socket
import struct
import subprocess
import time
from threading import Condition, Lock

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal


def list_serial_ports() -> list[str]:
    devices = []
    for port in serial.tools.list_ports.comports():
        device = port.device
        lowered = device.lower()
        if "bluetooth" in lowered or "debug-console" in lowered:
            continue
        devices.append(device)
    devices.sort(key=lambda name: (0 if "usb" in name.lower() else 1, name))
    return devices


def _ipv4_subnets() -> list[tuple[int, int, str]]:
    """Сети компьютера: адрес, маска и широковещательный адрес."""
    try:
        text = subprocess.check_output(["ifconfig"], text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in text.splitlines():
        parts = line.split()
        if "inet" not in parts or "netmask" not in parts:
            continue
        ip = parts[parts.index("inet") + 1]
        mask = parts[parts.index("netmask") + 1]
        if ip.startswith("127."):
            continue
        try:
            ip_i = struct.unpack("!I", socket.inet_aton(ip))[0]
            mask_i = int(mask, 16) if mask.startswith("0x") else struct.unpack("!I", socket.inet_aton(mask))[0]
        except (OSError, ValueError):
            continue
        broadcast = socket.inet_ntoa(struct.pack("!I", (ip_i | (~mask_i & 0xFFFFFFFF)) & 0xFFFFFFFF))
        found.append((ip_i, mask_i, broadcast))
    return found


def subnet_broadcast(host: str, subnets: list[tuple[int, int, str]] | None = None) -> str | None:
    """Широковещательный адрес той сети, где находится плата."""
    try:
        host_i = struct.unpack("!I", socket.inet_aton(host))[0]
    except OSError:
        return None
    for ip_i, mask_i, broadcast in subnets if subnets is not None else _ipv4_subnets():
        if mask_i and (host_i & mask_i) == (ip_i & mask_i):
            return broadcast
    return None


def local_address(host: str) -> str | None:
    """Адрес компьютера в той же сети, что и плата."""
    try:
        host_i = struct.unpack("!I", socket.inet_aton(host))[0]
    except OSError:
        return None
    for ip_i, mask_i, _broadcast in _ipv4_subnets():
        if mask_i and (host_i & mask_i) == (ip_i & mask_i):
            return socket.inet_ntoa(struct.pack("!I", ip_i))
    return None


def _broadcast_targets() -> list[str]:
    targets = ["255.255.255.255"]
    for _ip, _mask, broadcast in _ipv4_subnets():
        if broadcast not in targets:
            targets.insert(0, broadcast)
    return targets


class LanSender:
    """UDP на плату. Если прямой адрес недостижим, шлёт в её локальную сеть."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._bound = ""
        self._via: dict[str, str] = {}
        self.note = ""

    def _ensure(self, host: str) -> None:
        local = local_address(host) or ""
        if self._sock is not None and self._bound == local:
            return
        self.close()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if local:
            self._sock.bind((local, 0))
        self._bound = local

    def send(self, host: str, port: int, packet: bytes) -> None:
        self._ensure(host)
        assert self._sock is not None
        dest = self._via.get(host, host)
        try:
            self._sock.sendto(packet, (dest, int(port)))
            return
        except OSError as exc:
            if dest != host or exc.errno not in (
                errno.EHOSTUNREACH,
                errno.ENETUNREACH,
                errno.EHOSTDOWN,
            ):
                raise
        broadcast = subnet_broadcast(host)
        if not broadcast or broadcast == host:
            raise OSError(errno.EHOSTUNREACH, "Нет маршрута до платы")
        self._via[host] = broadcast
        self.note = broadcast
        self._sock.sendto(packet, (broadcast, int(port)))

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def discover_boards(timeout: float = 2.4, port: int = 4210) -> list[tuple[str, int]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    found: list[tuple[str, int]] = []
    seen: set[str] = set()
    targets = _broadcast_targets()
    try:
        deadline = time.monotonic() + timeout
        next_send = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:
                for target in targets:
                    try:
                        sock.sendto(b"AMP?", (target, int(port)))
                    except OSError:
                        continue
                next_send = time.monotonic() + 0.4
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            text = data.decode("utf-8", "ignore").strip()
            if not text.startswith("AMP,"):
                continue
            parts = text.split(",")
            if len(parts) < 3 or addr[0] in seen:
                continue
            try:
                leds = int(parts[2])
            except ValueError:
                leds = 0
            seen.add(addr[0])
            found.append((addr[0], leds))
    finally:
        sock.close()
    return found


class Sender(QThread):
    """Держит порт открытым и отправляет только последний пакет."""

    status = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._wake = Condition(self._lock)
        self._packet: bytes | None = None
        self._stop = False
        self._on_idle = None
        self._cfg = {
            "active": False,
            "serial_on": True,
            "port": "",
            "udp_on": False,
            "host": "",
            "udp_port": 4210,
        }
        self._ser = None
        self._open_port = ""
        self._lan = LanSender()
        self._retry_at = 0.0
        self._last_status = ""

    def configure(self, **kwargs) -> None:
        with self._wake:
            self._cfg.update(kwargs)
            if not self._cfg["active"]:
                self._packet = None
            self._wake.notify()

    def stop_output(self, packet: bytes | None = None) -> None:
        """Шлёт последний пакет, если он есть, и закрывает порт."""
        with self._wake:
            self._cfg["active"] = False
            self._packet = packet
            self._wake.notify()

    def submit(self, packet: bytes) -> None:
        with self._wake:
            if not self._cfg["active"]:
                return
            self._packet = packet
            self._wake.notify()

    def release_port(self, timeout: float = 2.0) -> bool:
        from threading import Event

        done = Event()
        with self._wake:
            self._cfg["active"] = False
            self._packet = None
            self._on_idle = done.set
            self._wake.notify()
        return done.wait(timeout)

    def stop(self) -> None:
        with self._wake:
            self._stop = True
            self._wake.notify()
        self.wait(3000)

    def _say(self, text: str) -> None:
        if text == self._last_status:
            return
        self._last_status = text
        self.status.emit(text)

    def run(self) -> None:
        while True:
            with self._wake:
                if self._stop:
                    break
                if self._packet is None and not self._stop:
                    self._wake.wait(0.3)
                if self._stop:
                    break
                packet = self._packet
                self._packet = None
                cfg = dict(self._cfg)
            if not cfg["active"]:
                if packet is not None:
                    self._dispatch(cfg, packet)
                self._close_serial(announce=True)
                with self._wake:
                    callback = self._on_idle
                    self._on_idle = None
                if callback:
                    callback()
                continue
            if packet is None:
                continue
            self._dispatch(cfg, packet)
        self._close_serial(announce=False)
        self._lan.close()

    def _dispatch(self, cfg: dict, packet: bytes) -> None:
        if cfg["serial_on"] and cfg["port"]:
            self._write_serial(str(cfg["port"]), packet)
        else:
            self._close_serial(announce=False)
        if cfg["udp_on"] and cfg["host"]:
            self._write_udp(str(cfg["host"]), int(cfg["udp_port"]), packet)

    def _write_serial(self, port: str, packet: bytes) -> None:
        now = time.monotonic()
        if self._ser is None or self._open_port != port:
            if now < self._retry_at:
                return
            self._close_serial(announce=False)
            try:
                self._say(f"Открываю {port}. Плата на секунду перезагрузится")
                self._ser = serial.Serial(port, 115200, timeout=0, write_timeout=0.25)
                self._open_port = port
                time.sleep(1.0)
                self._say(f"Arduino подключена: {port}")
            except Exception as exc:
                self._ser = None
                self._open_port = ""
                self._retry_at = time.monotonic() + 1.5
                self._say(f"Не открылся порт {port}: {exc}")
                return
        try:
            self._ser.write(packet)
        except Exception as exc:
            self._close_serial(announce=False)
            self._retry_at = time.monotonic() + 1.5
            self._say(f"Ошибка записи в порт: {exc}")

    def _close_serial(self, announce: bool) -> None:
        if self._ser is None:
            return
        try:
            self._ser.close()
        except Exception:
            pass
        self._ser = None
        self._open_port = ""
        if announce:
            self._say("Передача остановлена, порт закрыт")

    def _write_udp(self, host: str, port: int, packet: bytes) -> None:
        try:
            self._lan.send(host, port, packet)
        except Exception as exc:
            self._say(f"Wi-Fi: {exc}")
            return
        if self._lan.note:
            self._say(f"Прямой адрес платы закрыт, цвет идёт через {self._lan.note}.")


class FindThread(QThread):
    found = pyqtSignal(object)

    def __init__(self, port: int) -> None:
        super().__init__()
        self._port = port

    def run(self) -> None:
        try:
            self.found.emit(discover_boards(port=self._port))
        except Exception as exc:
            self.found.emit(exc)
