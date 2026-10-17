"""Клиент JSON API Hyperion (порт 19444).

Цвет, эффект и кадр экрана идут в выбранный экземпляр.
"""

from __future__ import annotations

import base64
import errno
import json
import socket
import threading

ORIGIN = "Ampilight"
DEFAULT_HOST = "192.168.100.7"
DEFAULT_PORT = 19444
DEFAULT_PASSWORD = "hyperion"
DEFAULT_INSTANCE = 1
# 128 — приоритет Home Assistant. Меньшее число было бы выше и не давало бы выключить стол.
DEFAULT_PRIORITY = 128
SCREEN_MODE = "Адаптив"
TV_ADAPTIVE = "Адаптив"
LEGACY_SCREEN = "Адаптив ноутбук"
SCREEN_NAMES = {SCREEN_MODE, "адаптив", LEGACY_SCREEN}
DESK_NAME = "Стол"
DESK_LEDS = 27
_SCREEN_SCRIPT = (
    "import hyperion, time\n"
    "hyperion.setColor(0, 0, 0)\n"
    "while not hyperion.abort():\n"
    "    time.sleep(0.2)\n"
)


class HyperionClient:
    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._pending = b""
        self._closed = True
        self._lock = threading.RLock()
        self.host = DEFAULT_HOST
        self.port = DEFAULT_PORT
        self.password = DEFAULT_PASSWORD
        self.instance = DEFAULT_INSTANCE
        self.modes: list[str] = []
        self.lit_priority: int | None = None
        self._blocker: tuple[int, int, str] | None = None
        self._manual = False
        self._leds_off: set[int] = set()
        self._led_counts: dict[int, int] = {}
        self._led_boxes: dict[int, list[tuple[float, float, float, float]]] = {}
        self._suspended: set[int] = set()
        self._force_show = False

    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._closed

    def close(self) -> None:
        with self._lock:
            self._closed = True
            sock = self._sock
            self._sock = None
            self._pending = b""
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def connect(self, host: str, port: int, password: str) -> list[tuple[int, str]]:
        host = host.strip()
        if not host:
            raise RuntimeError("Укажите адрес сервера")
        self.host = host
        self.port = int(port)
        self.password = password
        self._closed = False
        self.lit_priority = None
        self._blocker = None
        self._manual = False
        self._leds_off.clear()
        self._led_counts.clear()
        self._led_boxes.clear()
        self._suspended.clear()
        self._force_show = False
        try:
            self._open()
            info = self._rpc({"command": "serverinfo"})
            if not info.get("success"):
                raise RuntimeError(_error_text(info, "Hyperion не ответил"))
            strips = _strips(info)
            for number, _name in strips:
                started = self._rpc(
                    {"command": "instance", "subcommand": "startInstance", "instance": number}
                )
                if started.get("success"):
                    continue
                error = _error_text(started, "").lower()
                if "running" in error or "active" in error:
                    continue
            if strips:
                self.instance = strips[0][0]
            self.modes = _modes(info)
            return strips or [(0, "Лента")]
        except Exception:
            self.close()
            raise

    def set_color(self, rgb: tuple[int, int, int], priority: int, instance: int | None = None) -> None:
        red, green, blue = (max(0, min(255, int(part))) for part in rgb)
        priority = max(1, min(255, int(priority)))
        target = self.instance if instance is None else int(instance)
        self._release_blocker(target)
        if self.lit_priority is not None and self.lit_priority != priority and self.instance == target:
            self._clear(self.lit_priority)
        self.instance = target
        reply = self._call(
            {
                "command": "color",
                "color": [red, green, blue],
                "priority": priority,
                "origin": ORIGIN,
                "duration": -1,
                "instance": [self.instance],
            }
        )
        if not reply.get("success"):
            raise RuntimeError(_error_text(reply, "Hyperion отклонил цвет"))
        self.lit_priority = priority
        self._blocker = (self.instance, priority, "COLOR")
        if self.instance == 1:
            try:
                self._clear(100)
            except RuntimeError:
                pass
        self._show_ours()

    def set_effect(self, name: str, priority: int, instance: int | None = None) -> None:
        target = self.instance if instance is None else int(instance)
        self._release_blocker(target)
        self.instance = target
        priority = max(1, min(255, int(priority)))
        reply = self._call(
            {
                "command": "effect",
                "effect": {"name": name},
                "priority": priority,
                "origin": ORIGIN,
                "duration": -1,
                "instance": [self.instance],
            }
        )
        if not reply.get("success"):
            raise RuntimeError(_error_text(reply, "Hyperion не включил режим"))
        self.lit_priority = priority
        self._blocker = (self.instance, priority, "EFFECT")
        if self.instance == 1 and name not in SCREEN_NAMES:
            try:
                self._clear(100)
            except RuntimeError:
                pass
        self._show_ours()

    def set_image(
        self,
        rgb: bytes,
        width: int,
        height: int,
        priority: int,
        instance: int | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        """Один ряд пикселей: слева направо, по пикселю на диод."""
        target = self.instance if instance is None else int(instance)
        priority = max(1, min(253, int(priority)))
        width = int(width)
        height = int(height)
        if width < 1 or height < 1 or len(rgb) != width * height * 3:
            raise ValueError("размер кадра не сходится")
        payload = {
            "command": "image",
            "instance": [target],
            "priority": priority,
            "origin": SCREEN_MODE,
            "duration": -1,
            "imagewidth": width,
            "imageheight": height,
            "imagedata": base64.b64encode(rgb).decode("ascii"),
        }
        with self._lock:
            if gate is not None and gate.is_set():
                return
            fresh = self._blocker != (target, priority, "IMAGE")
            if fresh:
                self._release_blocker(target)
            if gate is not None and gate.is_set():
                return
            self.instance = target
            reply = self._call(payload)
            if not reply.get("success"):
                raise RuntimeError(_error_text(reply, "Hyperion не принял экран"))
            self.lit_priority = priority
            self._blocker = (target, priority, "IMAGE")
            if fresh or self._force_show:
                self._show_ours()

    def led_count(self, instance: int) -> int:
        """Сколько диодов у этой ленты. Для стола это 27 в один ряд."""
        number = int(instance)
        cached = self._led_counts.get(number)
        if cached:
            return cached
        reply = self._rpc({"command": "serverinfo", "instance": number})
        count = _led_total(reply)
        if count < 1:
            count = DESK_LEDS
        self._led_counts[number] = count
        return count

    def led_boxes(self, instance: int) -> list[tuple[float, float, float, float]]:
        """Прямоугольники диодов на кадре: куда Hyperion смотрит за цветом."""
        number = int(instance)
        cached = self._led_boxes.get(number)
        if cached is not None:
            return cached
        reply = self._rpc({"command": "serverinfo", "instance": number})
        boxes = _led_boxes(reply)
        self._led_boxes[number] = boxes
        return boxes

    def ensure_screen_effect(self) -> None:
        """Эффект «адаптив» в списке Hyperion, чтобы Home Assistant показал его у стола."""
        if SCREEN_MODE in self.modes:
            return
        try:
            reply = self._rpc(
                {
                    "command": "create-effect",
                    "name": SCREEN_MODE,
                    "script": _SCREEN_SCRIPT,
                    "args": {},
                }
            )
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
            return
        if not reply.get("success"):
            error = _error_text(reply, "").lower()
            if "exist" not in error and "already" not in error and "есть" not in error:
                return
        try:
            info = self._rpc({"command": "serverinfo"})
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
            return
        self.modes = _modes(info)

    def set_capture(self, instance: int, enabled: bool) -> None:
        """Захват телевизора. Выключен — на ленте виден цвет или эффект, как в Home Assistant."""
        self.instance = int(instance)
        self._component("V4L", bool(enabled))

    def mute_blackborder(self, instance: int) -> None:
        self.instance = int(instance)
        self._component("BLACKBORDER", False)

    def screen_status(self, instance: int) -> str:
        number = int(instance)
        reply = self._rpc({"command": "serverinfo", "instance": number})
        if not isinstance(reply.get("info"), dict):
            reply = self._rpc({"command": "serverinfo"})
        return screen_hold(reply, DEFAULT_PRIORITY)

    def inspect(self, instance: int) -> dict:
        number = int(instance)
        reply = self._rpc({"command": "serverinfo", "instance": number})
        if not isinstance(reply.get("info"), dict):
            reply = self._rpc({"command": "serverinfo"})
        state = live_state(reply, number)
        self._remember(state)
        return state

    def blank(self, instance: int) -> None:
        self.instance = int(instance)
        self._release_blocker(self.instance)
        if self.lit_priority is not None:
            self._clear(self.lit_priority)
            self.lit_priority = None
        if self.instance == 1:
            for priority in (50, 100, 128):
                try:
                    self._clear(priority)
                except RuntimeError:
                    pass
        self._component("LEDDEVICE", False)
        self._leds_off.add(self.instance)
        self._blocker = None
        if self.instance == 1:
            from app.desk_screen import push_black

            push_black(8)

    def wake(self, instance: int) -> None:
        self.instance = int(instance)
        try:
            self._rpc({"command": "instance", "subcommand": "startInstance", "instance": self.instance})
        except (OSError, RuntimeError, json.JSONDecodeError):
            pass
        if self.instance in self._suspended:
            self._component("ALL", True)
            self._suspended.discard(self.instance)
        self._component("LEDDEVICE", True)
        self._leds_off.discard(self.instance)
        self._force_show = True

    def clear(self, priority: int | None = None, instance: int | None = None, forget: bool = True) -> None:
        if instance is not None:
            self.instance = int(instance)
        target = self.lit_priority if priority is None else int(priority)
        if target is None:
            return
        self._clear(target)
        if forget and self.lit_priority == target:
            self.lit_priority = None

    def _remember(self, state: dict) -> None:
        instance = int(state["instance"])
        priority = state.get("priority")
        kind = str(state.get("kind") or "")
        if isinstance(priority, int):
            self._blocker = (instance, priority, kind)
        elif self._blocker is not None and self._blocker[0] == instance:
            self._blocker = None
        self._manual = bool(state.get("manual"))
        if state.get("leds") is False:
            self._leds_off.add(instance)
        else:
            self._leds_off.discard(instance)
        if state.get("suspended"):
            self._suspended.add(instance)
        else:
            self._suspended.discard(instance)

    def _release_blocker(self, instance: int) -> None:
        blocker = self._blocker
        if blocker is None:
            return
        inst, priority, kind = blocker
        if inst != int(instance) or kind not in {"COLOR", "EFFECT", "IMAGE"}:
            return
        self.instance = int(instance)
        try:
            self._clear(priority)
        except RuntimeError:
            pass
        self._blocker = None
        if self.lit_priority == priority:
            self.lit_priority = None

    def _show_ours(self) -> None:
        """Не запирать источник: иначе захват телевизора и Home Assistant перестают быть видны."""
        self._force_show = False
        if not self._manual:
            return
        try:
            self._rpc(
                {
                    "command": "sourceselect",
                    "auto": True,
                    "instance": [self.instance],
                }
            )
        except (OSError, RuntimeError, json.JSONDecodeError):
            return
        self._manual = False

    def _component(self, name: str, enabled: bool) -> None:
        body = {"component": name, "state": bool(enabled)}
        attempts = (
            {"command": "componentstate", "componentstate": body, "instance": [self.instance]},
            {"command": "componentstate", "componentstate": body, "instance": self.instance},
        )
        for payload in attempts:
            try:
                reply = self._rpc(payload)
            except (OSError, RuntimeError, json.JSONDecodeError):
                continue
            if reply.get("success") is not False:
                return
            error = _error_text(reply, "").lower()
            if "already" in error or "enabled" in error or "disabled" in error:
                return

    def _clear(self, priority: int) -> None:
        reply = self._call(
            {"command": "clear", "priority": int(priority), "instance": [self.instance]}
        )
        if not reply.get("success"):
            raise RuntimeError(_error_text(reply, "Hyperion не погасил цвет"))

    def _open(self) -> None:
        self._drop_socket()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=8)
        except ConnectionRefusedError as exc:
            raise RuntimeError("Сервер не принимает соединение. Проверьте адрес и порт.") from exc
        except TimeoutError as exc:
            raise RuntimeError("Сервер не отвечает.") from exc
        except OSError as exc:
            if exc.errno in {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}:
                raise RuntimeError("Сервер в сети не найден. Проверьте адрес и что Hyperion включён.") from exc
            raise RuntimeError(f"Нет связи с сервером: {exc}") from exc
        sock.settimeout(8)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        with self._lock:
            self._sock = sock
            self._pending = b""
            self._closed = False
        if self.password:
            reply = self._rpc(
                {"command": "authorize", "subcommand": "login", "password": self.password}
            )
            if not reply.get("success"):
                raise RuntimeError(_error_text(reply, "Hyperion не пустил"))

    def _drop_socket(self) -> None:
        with self._lock:
            sock = self._sock
            self._sock = None
            self._pending = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _call(self, command: dict) -> dict:
        if self._closed or self._sock is None:
            raise RuntimeError("Нет соединения")
        try:
            return self._rpc(command)
        except (OSError, RuntimeError, json.JSONDecodeError):
            if self._closed:
                raise RuntimeError("Нет соединения")
            self._open()
            return self._rpc(command)

    def _rpc(self, command: dict) -> dict:
        # Весь обмен под замком: кадр экрана и опрос состояния делят один сокет.
        with self._lock:
            sock = self._sock
            pending = self._pending
            if sock is None:
                raise RuntimeError("Нет соединения")
            try:
                sock.sendall((json.dumps(command, ensure_ascii=False) + "\n").encode())
                data = pending
                while b"\n" not in data:
                    chunk = sock.recv(1024 * 256)
                    if not chunk:
                        raise RuntimeError("Hyperion закрыл соединение")
                    data += chunk
            except TimeoutError as exc:
                raise RuntimeError("Сервер не отвечает.") from exc
            except OSError as exc:
                raise RuntimeError("Связь с Hyperion прервалась") from exc
            line, _, rest = data.partition(b"\n")
            if self._sock is sock:
                self._pending = rest
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                self._pending = b""
                raise
            if isinstance(reply.get("info"), dict):
                reply["info"].pop("token", None)
            return reply


def _led_total(info: dict) -> int:
    leds = _led_list(info)
    return len(leds) if isinstance(leds, list) else 0


def _led_list(info: dict) -> list | None:
    payload = info.get("info") if isinstance(info.get("info"), dict) else {}
    leds = payload.get("leds") if isinstance(payload, dict) else None
    return leds if isinstance(leds, list) else None


def _led_boxes(info: dict) -> list[tuple[float, float, float, float]]:
    leds = _led_list(info)
    if not leds:
        return []
    boxes: list[tuple[float, float, float, float]] = []
    for led in leds:
        if not isinstance(led, dict):
            return []
        if all(key in led for key in ("hmin", "hmax", "vmin", "vmax")):
            box = (
                float(led["hmin"]),
                float(led["hmax"]),
                float(led["vmin"]),
                float(led["vmax"]),
            )
        elif "x" in led and "y" in led:
            across, down = float(led["x"]), float(led["y"])
            box = (across - 0.02, across + 0.02, down - 0.02, down + 0.02)
        else:
            return []
        boxes.append(box)
    peak = max(max(box) for box in boxes)
    if peak > 1.5:
        boxes = [tuple(value / 100 for value in box) for box in boxes]
    return boxes


def _error_text(reply: dict, fallback: str) -> str:
    error = reply.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    return fallback


def _strips(info: dict) -> list[tuple[int, str]]:
    payload = info.get("info") if isinstance(info.get("info"), dict) else {}
    items = None
    if isinstance(payload, dict):
        items = payload.get("instance")
        if not isinstance(items, list):
            items = payload.get("instances")
    found: list[tuple[int, str]] = []
    if not isinstance(items, list):
        return found
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("instance", len(found)))
        except (TypeError, ValueError):
            continue
        name = item.get("friendly_name") or item.get("name")
        label = name.strip() if isinstance(name, str) and name.strip() else f"Лента {number}"
        found.append((number, label))
    return found


def _priority_name(item: dict) -> str:
    """Имя источника: у кадра оно приходит в origin, у эффекта — в owner."""
    for key in ("owner", "origin"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.split("@", 1)[0].strip()
    return ""


def screen_hold(info: dict, priority: int = DEFAULT_PRIORITY) -> str:
    """ours — адаптив на ленте. other — его место занял другой режим. cover — сверху чужой источник. gone — погашен."""
    payload = info.get("info") if isinstance(info.get("info"), dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    components: dict[str, bool] = {}
    for item in payload.get("components") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            components[item["name"]] = bool(item.get("enabled"))
    if components.get("LEDDEVICE") is False or components.get("ALL") is False:
        return "gone"
    priorities = payload.get("priorities") if isinstance(payload.get("priorities"), list) else []
    found = False
    for item in priorities:
        if not isinstance(item, dict):
            continue
        owner = _priority_name(item)
        try:
            number = int(item["priority"])
        except (KeyError, TypeError, ValueError):
            number = None
        visible = bool(item.get("visible"))
        if visible and owner not in SCREEN_NAMES and number is not None and number < int(priority):
            return "cover"
        if number == int(priority) and owner not in SCREEN_NAMES and visible:
            return "other"
        if owner in SCREEN_NAMES and item.get("active", True):
            found = True
    return "ours" if found else "gone"


def live_state(info: dict, instance: int) -> dict:
    """Что сейчас реально выведено на ленту этого экземпляра."""
    payload = info.get("info") if isinstance(info.get("info"), dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    components: dict[str, bool] = {}
    for item in payload.get("components") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            components[item["name"]] = bool(item.get("enabled"))
    leds = components.get("LEDDEVICE", True)
    suspended = components.get("ALL") is False
    priorities = payload.get("priorities") if isinstance(payload.get("priorities"), list) else []
    visible = None
    for item in priorities:
        if isinstance(item, dict) and item.get("visible"):
            visible = item
            break
    if visible is None and priorities and isinstance(priorities[0], dict):
        visible = priorities[0]
    mode = ""
    kind = ""
    rgb = None
    priority = None
    active = False
    if isinstance(visible, dict):
        kind = str(visible.get("componentId") or "")
        active = bool(visible.get("active", True))
        try:
            priority = int(visible["priority"])
        except (KeyError, TypeError, ValueError):
            priority = None
        owner = _priority_name(visible)
        if kind == "COLOR":
            mode = "Solid"
            rgb = _rgb_value(visible.get("value"))
        elif owner:
            mode = owner
        elif kind:
            mode = kind
    return {
        "instance": int(instance),
        "on": bool(leds and not suspended and active and visible is not None),
        "leds": leds and not suspended,
        "suspended": suspended,
        "mode": mode,
        "kind": kind,
        "rgb": rgb,
        "priority": priority,
        "manual": payload.get("priorities_autoselect") is False,
    }


def _rgb_value(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("RGB")
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    try:
        return tuple(max(0, min(255, int(part))) for part in raw[:3])
    except (TypeError, ValueError):
        return None


def _modes(info: dict) -> list[str]:
    payload = info.get("info") if isinstance(info.get("info"), dict) else {}
    items = payload.get("effects") if isinstance(payload, dict) else None
    names: list[str] = []
    if not isinstance(items, list):
        return names
    for item in items:
        if isinstance(item, str):
            label = item.strip()
        elif isinstance(item, dict):
            raw = item.get("name") or item.get("title")
            label = raw.strip() if isinstance(raw, str) else ""
        else:
            label = ""
        if label and label not in names:
            names.append(label)
    return names
