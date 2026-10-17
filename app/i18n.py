"""Русский интерфейс по умолчанию. На английской системе те же надписи по-английски."""

from __future__ import annotations

import os

_force: bool | None = None

_EN = {
    "Ищем Hyperion…": "Looking for Hyperion…",
    "Подключиться вручную": "Connect manually",
    "Нажми «Разрешить» у значка глобуса": "Click Allow next to the globe icon",
    "Сервер не найден": "Server not found",
    "В сети": "Online",
    "Яркость": "Brightness",
    "Красный": "Red",
    "Оранжевый": "Orange",
    "Жёлтый": "Yellow",
    "Зелёный": "Green",
    "Голубой": "Cyan",
    "Синий": "Blue",
    "Фиолетовый": "Purple",
    "Белый": "White",
    "Режим {name}": "Mode {name}",
    "На ленте {red}, {green}, {blue}": "On the strip {red}, {green}, {blue}",
    "Лента погашена": "Strip off",
    "Отключено": "Disconnected",
    "Ошибка Hyperion": "Hyperion error",
    "Показать пароль": "Show password",
    "Скрыть пароль": "Hide password",
    "Включить": "Turn on",
    "Выключить": "Turn off",
    "Адрес": "Address",
    "Порт": "Port",
    "Пароль": "Password",
    "Подключить": "Connect",
    "Назад к поиску": "Back to search",
    "Прибор": "Device",
    "Режим": "Mode",
    "Настройки": "Settings",
    "Цвет": "Color",
    "Назад": "Back",
    "Диоды": "LEDs",
    "Слева": "Left",
    "Сверху": "Top",
    "Справа": "Right",
    "Снизу": "Bottom",
    "Диод 1 — правый край стола, дальше цепочка идёт влево.": "LED 1 is the right edge of the desk. The chain runs left.",
    "Область захвата": "Capture area",
    "Диапазон ленты": "Strip range",
    "Захват и лента задаются одинаковым диапазоном.": "Capture and the strip use the same range.",
    "Готово": "Done",
    "Экран {start}–{end}% идёт на диоды {first}–{last}. Остальные гаснут.": "Screen {start}–{end}% goes to LEDs {first}–{last}. The rest stay off.",
    "Отключение…": "Disconnecting…",
    "Укажите адрес сервера": "Enter the server address",
    "Подключение…": "Connecting…",
    "Нет режимов": "No modes",
    "Разрешите Hyperion запись экрана в настройках системы": "Allow Hyperion to record the screen in System Settings",
    "захват экрана не запустился": "screen capture did not start",
    "Hyperion не принял экран": "Hyperion rejected the screen",
    "На связи, лента погашена": "Connected, strip is off",
    "Остановить": "Stop",
    "Запустить": "Start",
    "Захват выключен": "Capture off",
    "Открыть": "Open",
    "Выйти": "Quit",
    "Захват включён": "Capture on",
    "Стол": "Desk",
    "Телевизор": "TV",
    "Адаптив": "Adaptive",
    "Адаптив ноутбук": "Laptop adaptive",
    "адаптив": "Adaptive",
    "Ноутбук": "Laptop",
    "Лента": "Strip",
    "Лента {number}": "Strip {number}",
    "Hyperion не ответил": "Hyperion did not respond",
    "Hyperion отклонил цвет": "Hyperion rejected the color",
    "Hyperion не включил режим": "Hyperion did not start the mode",
    "Hyperion не погасил цвет": "Hyperion did not turn the color off",
    "Сервер не принимает соединение. Проверьте адрес и порт.": "The server is not accepting the connection. Check the address and port.",
    "Сервер не отвечает.": "The server is not responding.",
    "Сервер в сети не найден. Проверьте адрес и что Hyperion включён.": "No server found on the network. Check the address and that Hyperion is running.",
    "Нет связи с сервером: {exc}": "No connection to the server: {exc}",
    "Hyperion не пустил": "Hyperion refused the login",
    "Нет соединения": "Not connected",
    "Hyperion закрыл соединение": "Hyperion closed the connection",
    "Связь с Hyperion прервалась": "The connection to Hyperion dropped",
    "На ленте": "On the strip",
    "Подключено": "Connected",
}


def use_english() -> bool:
    if _force is not None:
        return _force
    try:
        from PyQt6.QtCore import QLocale

        name = QLocale.system().name()
    except Exception:
        name = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    return name.lower().startswith("en")


def tr(text: str) -> str:
    if not text or not use_english():
        return text
    key = text.replace("\u200b", "").strip()
    return _EN.get(key, text)
