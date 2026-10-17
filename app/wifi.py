"""Сеть Wi-Fi, к которой сейчас подключён этот компьютер."""

from __future__ import annotations

import json
import subprocess

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ModuleNotFoundError:
    QThread = object
    pyqtSignal = None


def wifi_device() -> str:
    try:
        proc = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "en0"
    want = False
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Hardware Port:") and ("Wi-Fi" in stripped or "AirPort" in stripped):
            want = True
            continue
        if want and stripped.startswith("Device:"):
            return stripped.split(":", 1)[1].strip() or "en0"
        if want and stripped.startswith("Hardware Port:"):
            want = False
    return "en0"


def _ssid_from_ipconfig(device: str) -> str:
    try:
        proc = subprocess.run(
            ["ipconfig", "getsummary", device],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if "BSSID" in stripped or not stripped.startswith("SSID"):
            continue
        _key, sep, value = stripped.partition(":")
        if sep:
            name = value.strip()
            if name:
                return name
    return ""


def _ssid_from_profiler() -> str:
    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPAirPortDataType", "-json"],
            text=True,
            timeout=20,
        )
        data = json.loads(raw)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, subprocess.CalledProcessError):
        return ""
    for group in data.get("SPAirPortDataType") or []:
        for iface in group.get("spairport_airport_interfaces") or []:
            current = iface.get("spairport_current_network_information") or {}
            name = str(current.get("_name") or "").strip()
            if name:
                return name
    return ""


def _real(name: str) -> str:
    # Без доступа к геопозиции macOS отдаёт "<redacted>" вместо имени сети.
    return "" if name == "<redacted>" else name


def current_ssid(allow_slow: bool = True) -> str:
    name = _real(_ssid_from_ipconfig(wifi_device()))
    if name or not allow_slow:
        return name
    return _real(_ssid_from_profiler())


def known_networks() -> list[str]:
    try:
        proc = subprocess.run(
            ["networksetup", "-listpreferredwirelessnetworks", wifi_device()],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = proc.stdout.splitlines()[1:]
    # Пробелы в конце — часть имени сети, срезаем только отступ.
    return [line.removeprefix("\t") for line in lines if line.strip()]


def keychain_password(ssid: str) -> str:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-D", "AirPort network password", "-a", ssid, "-w"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def scan_networks() -> list[str]:
    name = current_ssid()
    return [name] if name else []


class WifiThread(QThread):
    if pyqtSignal is not None:
        found = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.found.emit(scan_networks())
        except Exception as exc:
            self.found.emit(exc)
