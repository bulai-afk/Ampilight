"""Экран ноутбука на «Стол» через Hyperion.

Цвета столбцов экрана уходят на диоды как есть, без второй гаммы.
"""

from __future__ import annotations

import base64
import ctypes
import json
import plistlib
import signal
import socket
import time
from pathlib import Path

import numpy as np

from app.hyperion import _led_boxes
from app.sck import ScreenStream, encode_strip, fit_leds

HOST = "192.168.100.7"
PORT = 19444
DESK = 1
SCREEN_PRIORITY = 100
ESP_HOST = "192.168.100.5"
ESP_PORT = 4048
DISCOVERY_PORT = 4210
LED_COUNT = 27
LAPTOP_MODES = {"Адаптив ноутбук", "Адаптив", "адаптив"}
ORIGIN = "Ноутбук"
PASSWORD = "hyperion"

_stop = False


def _handle_stop(_signum, _frame) -> None:
    global _stop
    _stop = True


FRAME_STALL_SEC = 1.2
SLEEP_GAP_SEC = 3.0


def main_display() -> int:
    core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    core.CGMainDisplayID.restype = ctypes.c_uint32
    return int(core.CGMainDisplayID())


def display_asleep() -> bool:
    """Крышка закрыта: системный экран спит, а плата сама кадр не сбрасывает."""
    core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    core.CGMainDisplayID.restype = ctypes.c_uint32
    core.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
    core.CGDisplayIsAsleep.restype = ctypes.c_int
    try:
        return bool(core.CGDisplayIsAsleep(core.CGMainDisplayID()))
    except (OSError, AttributeError):
        return False


def should_drop_capture(
    asleep: bool,
    sending: bool,
    last_frame_at: float,
    last_loop_at: float,
    now: float,
) -> bool:
    """Сон, закрытая крышка или оборванный кадр. Иначе лента замирает на последней картинке."""
    if asleep:
        return True
    if last_loop_at and now - last_loop_at > SLEEP_GAP_SEC:
        return True
    if sending and last_frame_at and now - last_frame_at > FRAME_STALL_SEC:
        return True
    return False


_SETTINGS = Path.home() / "Library/Preferences/com.ampilight.hyperion.lan.Ampilight.plist"
_CAPTURE_FLAG = Path("/tmp/ampilight-capturing")
_PREVIEW = Path("/tmp/ampilight-preview.ppm")


def _write_preview(frame: np.ndarray, capture_start: int, capture_end: int) -> None:
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if height < 1 or width < 1:
        return
    y0 = int(height * capture_start / 100)
    y1 = int(round(height * capture_end / 100))
    y0 = max(0, min(height - 1, y0))
    y1 = max(y0 + 1, min(height, y1))
    band = frame[y0:y1]
    step_x = max(1, band.shape[1] // 320)
    step_y = max(1, band.shape[0] // 64)
    small = np.ascontiguousarray(band[::step_y, ::step_x, :3])
    rows, cols = int(small.shape[0]), int(small.shape[1])
    body = small.astype(np.uint8, copy=False).tobytes()
    try:
        _PREVIEW.write_bytes(f"P6\n{cols} {rows}\n255\n".encode() + body)
    except OSError:
        pass


def _mark_capture(active: bool) -> None:
    try:
        if active:
            _CAPTURE_FLAG.write_text("1", encoding="ascii")
        else:
            _CAPTURE_FLAG.unlink(missing_ok=True)
            _PREVIEW.unlink(missing_ok=True)
    except OSError:
        pass


def _setting(data: dict, key: str, default: int) -> int:
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def strip_fit() -> tuple[int, int, int, int, int, int, int, int, int]:
    """Те же ползунки, что в программе: низ экрана, диапазон, число диодов."""
    data: dict = {}
    try:
        data = plistlib.loads(_SETTINGS.read_bytes())
    except (OSError, plistlib.InvalidFileException):
        data = {}
    percent = _setting(data, "hyperion_bottom_percent", 15)
    capture_start = data.get("hyperion_capture_start")
    capture_end = data.get("hyperion_capture_end")
    if capture_start is None or capture_end is None:
        capture_start = max(0, 100 - percent)
        capture_end = 100
    return (
        _setting(data, "hyperion_leds_bottom", 27),
        _setting(data, "hyperion_leds_left", 0),
        _setting(data, "hyperion_leds_top", 0),
        _setting(data, "hyperion_leds_right", 0),
        percent,
        _setting(data, "hyperion_span_start", 0),
        _setting(data, "hyperion_span_end", 100),
        _setting({"hyperion_capture_start": capture_start}, "hyperion_capture_start", 85),
        _setting({"hyperion_capture_end": capture_end}, "hyperion_capture_end", 100),
    )


class Hyperion:
    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._pending = b""

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        self._pending = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _connect(self) -> None:
        self.close()
        sock = socket.create_connection((HOST, PORT), timeout=8)
        sock.settimeout(8)
        self._sock = sock
        reply = self._rpc({"command": "authorize", "subcommand": "login", "password": PASSWORD})
        if not reply.get("success"):
            raise RuntimeError("Hyperion не пустил")

    def _rpc(self, command: dict) -> dict:
        sock = self._sock
        if sock is None:
            raise RuntimeError("нет соединения")
        expect = command.get("command")
        sock.sendall((json.dumps(command, ensure_ascii=False) + "\n").encode())
        deadline = time.monotonic() + 8
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Hyperion не ответил")
                sock.settimeout(remaining)
                data = self._pending
                while b"\n" not in data:
                    chunk = sock.recv(1024 * 256)
                    if not chunk:
                        raise RuntimeError("Hyperion закрыл соединение")
                    data += chunk
                line, _, self._pending = data.partition(b"\n")
                reply = json.loads(line)
                if isinstance(reply.get("info"), dict):
                    reply["info"].pop("token", None)
                got = reply.get("command")
                if expect and got != expect and not (
                    isinstance(got, str) and got.startswith(f"{expect}-")
                ):
                    continue
                return reply
        finally:
            sock.settimeout(8)

    def call(self, command: dict) -> dict:
        if self._sock is None:
            self._connect()
        try:
            return self._rpc(command)
        except (OSError, RuntimeError, json.JSONDecodeError):
            self._connect()
            return self._rpc(command)


def discover_esp(timeout: float = 0.8) -> str | None:
    """Плата отвечает «AMP,адрес,27». Адрес по DHCP меняется, старый тогда молчит."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    try:
        sock.sendto(b"AMP?", ("192.168.100.255", DISCOVERY_PORT))
        found: str | None = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                break
            parts = data.decode("ascii", "ignore").split(",")
            if len(parts) >= 3 and parts[0] == "AMP" and parts[2].strip() == str(LED_COUNT):
                found = parts[1].strip() or addr[0]
        return found
    except OSError:
        return None
    finally:
        sock.close()


def point_hyperion(link: Hyperion, host: str) -> None:
    """Hyperion иначе продолжает слать кадры на прежний адрес, и лента застывает."""
    try:
        reply = link.call({"command": "config", "subcommand": "getconfig"})
    except (OSError, RuntimeError, json.JSONDecodeError):
        return
    info = reply.get("info")
    if not isinstance(info, dict):
        return
    changed = False
    for item in info.get("instances") or []:
        if not isinstance(item, dict) or item.get("id") != DESK:
            continue
        device = (item.get("settings") or {}).get("device")
        if isinstance(device, dict) and device.get("type") == "udpddp" and device.get("host") != host:
            device["host"] = host
            changed = True
    if not changed:
        return
    try:
        link.call({"command": "config", "subcommand": "setconfig", "config": info})
    except (OSError, RuntimeError, json.JSONDecodeError):
        link.close()
        return
    print(f"стол: плата {host}", flush=True)


def refresh_esp(link: Hyperion | None = None) -> str:
    global ESP_HOST
    found = discover_esp()
    if not found:
        return ESP_HOST
    if found != ESP_HOST:
        ESP_HOST = found
        if link is not None:
            point_hyperion(link, found)
    return ESP_HOST


def ddp_black(count: int = LED_COUNT) -> bytes:
    """Чёрный кадр DDP. Плата иначе держит последний цвет, когда Hyperion замолкает."""
    payload = bytes(max(1, count) * 3)
    header = bytearray(10)
    header[0] = 0x01
    header[1] = 1
    header[2] = 1
    header[8] = (len(payload) >> 8) & 0xFF
    header[9] = len(payload) & 0xFF
    return bytes(header) + payload


def push_black(times: int = 8) -> None:
    packet = ddp_black()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _ in range(max(1, times)):
            try:
                sock.sendto(packet, (ESP_HOST, ESP_PORT))
            except OSError:
                pass
            time.sleep(0.02)
    finally:
        sock.close()


def _hold_black(link: Hyperion) -> None:
    """Снять застывший кадр и залить ленту чёрным. Режим «Адаптив» при этом не выключается."""
    try:
        link.call({"command": "clear", "priority": SCREEN_PRIORITY, "instance": [DESK]})
    except (OSError, RuntimeError, json.JSONDecodeError):
        link.close()
    push_black()


def _release_output(link: Hyperion) -> None:
    """Выключить выход и залить чёрным. Иначе Hyperion продолжает последний кадр."""
    try:
        link.call({"command": "clear", "priority": SCREEN_PRIORITY, "instance": [DESK]})
    except (OSError, RuntimeError, json.JSONDecodeError):
        link.close()
    try:
        link.call(
            {
                "command": "componentstate",
                "componentstate": {"component": "LEDDEVICE", "state": False},
                "instance": [DESK],
            }
        )
    except (OSError, RuntimeError, json.JSONDecodeError):
        link.close()
    push_black()


def _owner(item: dict) -> str:
    raw = item.get("owner") or item.get("origin") or ""
    return str(raw).split("@", 1)[0].strip()


def _rgb_of(item: dict) -> tuple[int, int, int] | None:
    value = item.get("value")
    if not isinstance(value, dict):
        return None
    raw = value.get("RGB")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        return tuple(max(0, min(255, int(part))) for part in raw[:3])
    except (TypeError, ValueError):
        return None


def desk_gate(info: dict) -> tuple[bool, bool, bool, tuple[int, int, int] | None]:
    """Адаптив, открыт ли выход на ленту, и есть ли команда с телефона или из программы.

    Home Assistant включает стол новым цветом или эффектом и не трогает выход.
    Если выход закрыт, лента остаётся тёмной, пока его не открыть.
    """
    body = info.get("info") if isinstance(info.get("info"), dict) else {}
    components: dict[str, bool] = {}
    for item in body.get("components") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            components[item["name"]] = bool(item.get("enabled"))
    leds_on = components.get("LEDDEVICE", True) and components.get("ALL", True)
    selected = False
    external = False
    other = False
    color: tuple[int, int, int] | None = None
    for item in body.get("priorities") or []:
        if not item.get("active", True):
            continue
        owner = _owner(item)
        try:
            priority = int(item.get("priority"))
        except (TypeError, ValueError):
            priority = None
        kind = item.get("componentId")
        if priority == SCREEN_PRIORITY and owner in {ORIGIN, "Ноутбук"}:
            continue
        if owner in LAPTOP_MODES and kind == "EFFECT":
            selected = True
            external = True
            continue
        if kind in {"COLOR", "EFFECT", "IMAGE"}:
            other = True
            external = True
            if kind == "COLOR" and color is None:
                color = _rgb_of(item)
    if other:
        selected = False
    return selected, leds_on, external, color


def main() -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    link = Hyperion()
    stream = ScreenStream()
    while not _stop:
        try:
            started = link.call({"command": "instance", "subcommand": "startInstance", "instance": DESK})
            if not started.get("success"):
                raise RuntimeError(started.get("error") or "стол не запустился")
            link.call(
                {
                    "command": "componentstate",
                    "componentstate": {"component": "BLACKBORDER", "state": False},
                    "instance": [DESK],
                }
            )
            link.call({"command": "clear", "priority": 120, "instance": [0, DESK]})
            print("стол: Hyperion готов", flush=True)
            break
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"стол: {exc}", flush=True)
            time.sleep(3)
            link.close()
    print("стол: жду режим «Адаптив»", flush=True)
    refresh_esp(link)
    next_discover = time.monotonic() + 15
    sending = False
    blanked = False
    image_on = True
    misses = 0
    boxes: list = []
    last_seq = 0
    sent = 0
    next_send = 0.0
    next_log = 0.0
    next_check = 0.0
    next_preview = 0.0
    last_frame_at = 0.0
    last_loop_at = time.time()
    dark = False
    try:
        while not _stop:
            now_wall = time.time()
            loop_gap = now_wall - last_loop_at
            last_loop_at = now_wall
            asleep = display_asleep()
            capture_dead = sending and not stream.running()
            if capture_dead or should_drop_capture(
                asleep, sending, last_frame_at, last_loop_at - loop_gap, now_wall
            ):
                if sending or stream.running():
                    sending = False
                    _mark_capture(False)
                    stream.stop()
                    print("стол: захват остановился", flush=True)
                if not dark or asleep:
                    _hold_black(link)
                    if not dark:
                        print("стол: экран погас, лента выключена", flush=True)
                    dark = True
                    image_on = False
                if asleep:
                    time.sleep(0.4)
                    last_loop_at = time.time()
                    continue
                last_frame_at = 0.0
            now = time.monotonic()
            if now >= next_discover:
                next_discover = now + 15
                refresh_esp(link)
            if now >= next_check:
                next_check = now + 0.8
                try:
                    link.call(
                        {"command": "instance", "subcommand": "switchTo", "instance": DESK}
                    )
                    info = link.call({"command": "serverinfo"})
                    selected, leds_on, external, color = desk_gate(info)
                    found = _led_boxes(info)
                    if found:
                        boxes = found
                except (OSError, RuntimeError, json.JSONDecodeError, TypeError) as exc:
                    print(f"стол: {exc}", flush=True)
                    link.close()
                    sending = False
                    time.sleep(2)
                    last_loop_at = time.time()
                    continue
                if not external:
                    misses += 1
                    if misses < 2:
                        continue
                    if sending:
                        sending = False
                        _mark_capture(False)
                        stream.stop()
                        print("стол: режим ноутбука выключен", flush=True)
                    if not blanked:
                        _release_output(link)
                        blanked = True
                        image_on = False
                        print("стол: лента погашена", flush=True)
                    continue
                misses = 0
                blanked = False
                if not leds_on:
                    try:
                        turned = link.call(
                            {
                                "command": "componentstate",
                                "componentstate": {"component": "LEDDEVICE", "state": True},
                                "instance": [DESK],
                            }
                        )
                    except (OSError, RuntimeError, json.JSONDecodeError):
                        link.close()
                        time.sleep(2)
                        last_loop_at = time.time()
                        continue
                    if turned.get("success") is not False:
                        leds_on = True
                        print("стол: выход на ленту открыт", flush=True)
                if not selected:
                    if sending:
                        sending = False
                        _mark_capture(False)
                        stream.stop()
                        print("стол: режим ноутбука выключен", flush=True)
                    if image_on:
                        try:
                            link.call(
                                {
                                    "command": "clear",
                                    "priority": SCREEN_PRIORITY,
                                    "instance": [DESK],
                                }
                            )
                        except (OSError, RuntimeError, json.JSONDecodeError):
                            link.close()
                        image_on = False
                        print("стол: заливка вместо захвата", flush=True)
                    continue
                if selected and not sending:
                    if dark:
                        _hold_black(link)
                    try:
                        stream.start(main_display(), max_edge=640, fps=12)
                    except RuntimeError as exc:
                        print(f"стол: {exc}", flush=True)
                        time.sleep(2)
                        last_loop_at = time.time()
                        continue
                    sending = True
                    image_on = True
                    dark = False
                    _mark_capture(True)
                    last_seq = 0
                    last_frame_at = time.time()
                    last_loop_at = time.time()
                    bottom, _left, _top, _right, _percent, span_start, span_end, capture_start, capture_end = strip_fit()
                    print(
                        f"стол: захват {capture_start}–{capture_end}%, диоды {bottom}, диапазон {span_start}–{span_end}, справа налево",
                        flush=True,
                    )
            if not sending:
                time.sleep(0.2)
                continue
            got = stream.take(last_seq, 0.4)
            if got is None:
                continue
            seq, frame = got
            last_seq = seq
            last_frame_at = time.time()
            dark = False
            now = time.monotonic()
            if now < next_send:
                continue
            next_send = now + 0.1
            bottom, left, top, right, percent, span_start, span_end, capture_start, capture_end = strip_fit()
            if now >= next_preview:
                next_preview = now + 0.4
                _write_preview(frame, capture_start, capture_end)
            raw = fit_leds(
                frame,
                bottom,
                left,
                top,
                right,
                percent,
                span_start,
                span_end,
                capture_start,
                capture_end,
                natural=True,
            )
            image, width, height = encode_strip(raw, boxes)
            try:
                reply = link.call(
                    {
                        "command": "image",
                        "instance": [DESK],
                        "priority": SCREEN_PRIORITY,
                        "origin": ORIGIN,
                        "duration": -1,
                        "imagewidth": width,
                        "imageheight": height,
                        "imagedata": base64.b64encode(image).decode("ascii"),
                    }
                )
            except (OSError, RuntimeError, json.JSONDecodeError) as exc:
                print(f"стол: {exc}", flush=True)
                link.close()
                sending = False
                stream.stop()
                time.sleep(2)
                last_loop_at = time.time()
                continue
            if not reply.get("success"):
                print(f"стол: кадр отклонён: {reply.get('error')}", flush=True)
                time.sleep(1)
                continue
            sent += 1
            if now >= next_log:
                print(f"стол: кадр {sent}", flush=True)
                next_log = now + 5
    finally:
        _mark_capture(False)
        stream.stop()
        try:
            link.call({"command": "clear", "priority": SCREEN_PRIORITY, "instance": [DESK]})
        except (OSError, RuntimeError, json.JSONDecodeError):
            pass
        link.close()
        print("стол: повтор экрана остановлен", flush=True)


if __name__ == "__main__":
    main()
