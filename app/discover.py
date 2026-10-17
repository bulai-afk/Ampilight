"""Поиск Hyperion в локальной сети: mDNS и опрос порта 19444."""

from __future__ import annotations

import errno
import json
import queue
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

JSON_PORT = 19444
_MDNS = ("224.0.0.251", 5353)
_SERVICES = ("_hyperiond-json._tcp.local", "_hyperiond-http._tcp.local")


def hosts_in_subnet(ip: int, mask: int) -> list[str]:
    """Адреса сети. Шире чем /24 режем до 254 штук, иначе поиск слишком долгий."""
    span = (~mask) & 0xFFFFFFFF
    if span == 0 or span > 255:
        mask = 0xFFFFFF00
        span = 255
    network = ip & mask
    found = []
    for offset in range(1, span):
        host = network + offset
        if host == ip:
            continue
        found.append(socket.inet_ntoa(struct.pack("!I", host & 0xFFFFFFFF)))
    return found


def has_lan_address(ip: int) -> bool:
    """Обычный адрес сети. Петля и link-local не считаются подключением."""
    if ip == 0 or (ip >> 24) == 127:
        return False
    return (ip >> 16) != 0xA9FE


def network_is_up() -> bool:
    return any(has_lan_address(ip) for ip, _mask in local_subnets())


def local_subnets() -> list[tuple[int, int]]:
    try:
        from app.sender import _ipv4_subnets

        found = [(ip, mask) for ip, mask, _broadcast in _ipv4_subnets() if mask]
        if found:
            return found
    except (OSError, ValueError):
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = struct.unpack("!I", socket.inet_aton(probe.getsockname()[0]))[0]
    except OSError:
        return []
    finally:
        probe.close()
    return [(ip, 0xFFFFFF00)]


def scan_targets(extra: str = "") -> list[str]:
    hosts: list[str] = []
    if extra:
        hosts.append(extra)
    for ip, mask in local_subnets():
        for host in hosts_in_subnet(ip, mask):
            if host not in hosts:
                hosts.append(host)
    return hosts


def looks_like_hyperion(payload: bytes) -> bool:
    if not payload:
        return False
    text = payload.decode("utf-8", "replace").lower()
    return "serverinfo" in text or "hyperion" in text or '"success"' in text


_LAN_DENIED = {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}
_denied = threading.Event()


def lan_access_denied() -> bool:
    return _denied.is_set()


def reset_lan_denial() -> None:
    _denied.clear()


def _connect(host: str, port: int, timeout: float, note_denial: bool = False) -> socket.socket | None:
    """Сокет к адресу. Мгновенный отказ сохранённого сервера — это запрет macOS."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    started = time.perf_counter()
    try:
        sock.connect((host, port))
    except OSError as exc:
        sock.close()
        if note_denial and exc.errno in _LAN_DENIED and time.perf_counter() - started < 0.05:
            _denied.set()
        return None
    return sock


def probe(host: str, port: int = JSON_PORT, timeout: float = 0.8, note_denial: bool = False) -> tuple[str, int] | None:
    """Имя сервера, если на порту отвечает Hyperion."""
    sock = _connect(host, port, timeout, note_denial)
    if sock is None:
        return None
    try:
        sock.settimeout(timeout)
        sock.sendall(b'{"command":"serverinfo"}\n')
        chunks: list[bytes] = []
        try:
            while sum(len(part) for part in chunks) < 262144:
                part = sock.recv(8192)
                if not part:
                    break
                chunks.append(part)
                if b"\n" in part:
                    break
        except OSError:
            pass
        payload = b"".join(chunks)
    finally:
        sock.close()
    if not looks_like_hyperion(payload):
        return None
    name = "Hyperion"
    devices = 0
    try:
        data = json.loads(payload.decode("utf-8", "replace").split("\n", 1)[0])
        info = data.get("info") if isinstance(data, dict) else None
        if isinstance(info, dict):
            host_name = info.get("hostname") or info.get("name")
            if isinstance(host_name, str) and host_name.strip():
                name = host_name.strip()
            strips = info.get("instance")
            if not isinstance(strips, list):
                strips = info.get("instances")
            if isinstance(strips, list):
                devices = len(strips)
    except (ValueError, AttributeError):
        pass
    return name, devices


def _encode_name(name: str) -> bytes:
    body = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".") if part)
    return body + b"\x00"


def _query(name: str) -> bytes:
    """PTR-запрос. Старший бит класса просит ответ прямо нам, а не в общий multicast."""
    return b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + _encode_name(name) + b"\x00\x0c\x80\x01"


def addresses_in_mdns(packet: bytes) -> list[str]:
    """IPv4 из A-записей. Чужие объявления без hyperion отбрасываем."""
    if b"hyperion" not in packet.lower():
        return []
    found = []
    start = 0
    marker = b"\x00\x01\x00\x01"
    while True:
        index = packet.find(marker, start)
        if index < 0 or index + 14 > len(packet):
            break
        if packet[index + 8 : index + 10] == b"\x00\x04":
            ip = socket.inet_ntoa(packet[index + 10 : index + 14])
            if ip not in found and not ip.startswith("0."):
                found.append(ip)
        start = index + 2
    return found


class ServerSearch(QThread):
    found = pyqtSignal(str, str, int, int)
    scan_finished = pyqtSignal()
    access_denied = pyqtSignal()

    def __init__(self, prefer: str = "") -> None:
        super().__init__()
        self._prefer = prefer.strip()
        self._stop = threading.Event()
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._told_denied = False
        self._hits: queue.Queue[tuple[str, str, int]] = queue.Queue()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        reset_lan_denial()
        if self._prefer:
            found = probe(self._prefer, timeout=2.0, note_denial=True)
            if found:
                name, devices = found
                self._hits.put((name, self._prefer, devices))
                self._drain()
        listener = threading.Thread(target=self._listen_mdns, daemon=True)
        listener.start()
        # Несколько проходов: диалог доступа к сети может появиться в середине первого.
        for attempt in range(15):
            if self._stop.is_set() or self._seen:
                break
            self._sweep()
            if self._stop.is_set() or self._seen or attempt == 14:
                break
            self._stop.wait(4)
            self._drain()
        if not self._stop.is_set():
            self.scan_finished.emit()
        self._stop.set()
        listener.join(timeout=0.2)

    def _sweep(self) -> None:
        targets = scan_targets(self._prefer)
        with ThreadPoolExecutor(max_workers=48) as pool:
            futures = [pool.submit(self._check, host) for host in targets]
            for future in as_completed(futures):
                if self._stop.is_set():
                    break
                future.result()
                self._drain()
        self._drain()

    def _check(self, host: str) -> None:
        if self._stop.is_set():
            return
        found = probe(host, timeout=1.5 if host == self._prefer else 0.4, note_denial=host == self._prefer)
        if found:
            name, devices = found
            self._hits.put((name, host, devices))

    def _drain(self) -> None:
        while True:
            try:
                name, host, devices = self._hits.get_nowait()
            except queue.Empty:
                break
            self._emit(name, host, devices)
        if self._seen:
            return
        if lan_access_denied() and not self._told_denied:
            self._told_denied = True
            self.access_denied.emit()

    def _emit(self, name: str, host: str, devices: int) -> None:
        with self._lock:
            if host in self._seen or self._stop.is_set():
                return
            self._seen.add(host)
        self.found.emit(name, host, JSON_PORT, devices)

    def _listen_mdns(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            try:
                sock.bind(("", 5353))
            except OSError:
                sock.bind(("", 0))
            try:
                group = struct.pack("=4s4s", socket.inet_aton("224.0.0.251"), socket.inet_aton("0.0.0.0"))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, group)
            except OSError:
                pass
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            sock.settimeout(0.4)
            announce_at = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= announce_at:
                    for name in _SERVICES:
                        try:
                            sock.sendto(_query(name), _MDNS)
                        except OSError:
                            return
                    announce_at = now + 4
                try:
                    packet, _addr = sock.recvfrom(9000)
                except OSError:
                    continue
                for host in addresses_in_mdns(packet):
                    found = probe(host, timeout=0.6)
                    if found:
                        name, devices = found
                        self._hits.put((name, host, devices))
        finally:
            sock.close()
