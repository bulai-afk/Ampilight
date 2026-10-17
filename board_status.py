#!/usr/bin/env python3
"""Подключена ли ESP32 к Wi-Fi. Плата должна быть воткнута в USB.

    python3 board_status.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import serial

REASONS = {
    "1": "сеть не видна: неверное имя или это сеть 5 ГГц (ESP32 видит только 2.4 ГГц)",
    "4": "неверный пароль Wi-Fi",
    "6": "роутер отключил плату, чаще всего из-за неверного пароля",
}


def find_port() -> str | None:
    for pattern in ("cu.usb*", "cu.wch*", "cu.SLAB*"):
        found = sorted(Path("/dev").glob(pattern))
        if found:
            return str(found[0])
    return None


def main() -> int:
    port = find_port()
    if port is None:
        print("Плата не видна по USB. Воткни кабель и запусти ещё раз.")
        return 1
    print(f"Плата на {port}. Перезагружаю и жду до 30 секунд…")
    ser = serial.Serial(port, 115200, timeout=0.2)
    ser.dtr = False
    ser.rts = True
    time.sleep(0.2)
    ser.rts = False
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            line = ser.readline().decode("utf-8", "replace").strip()
            if not line.startswith("AMPILIGHT"):
                continue
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "NOWIFI":
                reason = REASONS.get(parts[2], f"код {parts[2]}")
                print(f"НЕ подключена к Wi-Fi: {reason}.")
                return 1
            if len(parts) >= 2:
                print(f"Подключена к Wi-Fi. Адрес платы: {parts[1]}")
                return 0
    finally:
        ser.close()
    print("Плата ничего не ответила. Возможно, прошивка не та или плата не загрузилась.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
