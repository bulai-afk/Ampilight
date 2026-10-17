#!/usr/bin/env python3
"""Прошивка ESP32 из терминала.

    python3 flash_esp32.py

Спрашивает число диодов, пин, сеть и пароль, затем показывает сборку и запись.
Пароль в консоль не печатается. Пустой пароль берётся из связки ключей Mac.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.flash import flash_board
from app.wifi import current_ssid, keychain_password, known_networks


def ask(label: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    value = input(f"{label}{hint}: ").strip()
    return value or default


def ask_int(label: str, default: int, low: int, high: int) -> int:
    while True:
        raw = ask(label, str(default))
        try:
            value = int(raw)
        except ValueError:
            print(f"Нужно число от {low} до {high}.")
            continue
        if low <= value <= high:
            return value
        print(f"Нужно число от {low} до {high}.")


def usb_ports() -> list[str]:
    found = []
    for pattern in ("cu.usb*", "cu.wch*", "cu.SLAB*"):
        found.extend(Path("/dev").glob(pattern))
    return [str(path) for path in sorted(set(found))]


def choose_port(ports: list[str]) -> str:
    if len(ports) == 1:
        print(f"USB: {ports[0]}")
        return ports[0]
    print("USB-порты:")
    for index, port in enumerate(ports, start=1):
        print(f"  {index}. {port}")
    while True:
        raw = ask("Номер порта", "1")
        try:
            index = int(raw)
        except ValueError:
            index = 0
        if 1 <= index <= len(ports):
            return ports[index - 1]
        print("Нет такого номера.")


def choose_network() -> str:
    current = current_ssid(allow_slow=False)
    if current:
        return ask("Сеть Wi-Fi", current)
    networks = known_networks()[:8]
    if not networks:
        return ask("Сеть Wi-Fi")
    print("macOS не говорит имя текущей сети. Последние сохранённые:")
    for index, name in enumerate(networks, start=1):
        print(f"  {index}. {name}")
    raw = ask("Номер сети или имя", "1")
    if raw.isdigit() and 1 <= int(raw) <= len(networks):
        return networks[int(raw) - 1]
    return raw


def main() -> int:
    print("Прошивка ESP32")
    print("Enter оставляет значение в скобках.")
    print()
    leds = ask_int("Количество диодов", 90, 1, 512)
    pin = ask_int("Пин данных", 5, 0, 40)
    ssid = choose_network()
    if not ssid:
        print("Имя сети не указано.")
        return 1
    password = getpass.getpass("Пароль Wi-Fi (Enter — взять из связки ключей Mac): ")
    if not password:
        print("Достаю пароль из связки ключей. macOS может спросить пароль от Mac.")
        password = keychain_password(ssid)
        if password:
            print("Пароль найден.")
    if not password:
        print("Пароль не найден. Запусти ещё раз и введи его вручную.")
        return 1
    ports = usb_ports()
    if not ports:
        print("Плата не видна по USB. Проверь кабель и общую землю.")
        return 1
    port = choose_port(ports)
    print()
    print(f"Диодов: {leds}, пин: {pin}, порт: {port}")
    if ask("Прошить? да/нет", "да").lower() not in {"да", "д", "y", "yes"}:
        print("Отмена.")
        return 1
    print()
    print("Дальше пойдёт сборка, потом соединение с платой и строки Writing.")
    try:
        flash_board(
            board_id="esp32",
            port=port,
            leds=leds,
            pin=pin,
            order="GRB",
            ssid=ssid,
            password=password,
            udp_port=4210,
            ota_auth=password,
            log=lambda line: print(line, flush=True),
        )
    except Exception as exc:
        print(exc, flush=True)
        return 1
    print("Готово. USB можно отключить, питание ленты оставь.", flush=True)
    print("В окне цветов нажми «Найти ESP32» и выбери плату.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
