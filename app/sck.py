"""Потоковый захват экрана через ScreenCaptureKit.

Один снимок через mss занимает около 40 мс. Отдельный процесс отдаёт
кадры потоком, и обработка цвета успевает за 30–60 кадрами в секунду.
Сам Python этот системный поток не держит: так захват не зависает.
"""

from __future__ import annotations

import ctypes
import mmap
import os
import select
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build" / "sck-helper"
MAX_BYTES = 1600 * 1600 * 4
HEADER = 16
MAP_SIZE = HEADER + MAX_BYTES


def _bundled_helper() -> Path | None:
    """В установленном приложении захват уже собран, компилятор не нужен."""
    exe = Path(sys.executable).resolve()
    for candidate in (exe.parent / "sck-helper", exe.parent.parent / "Resources" / "sck-helper"):
        if candidate.is_file():
            return candidate
    return None


def ensure_helper() -> Path:
    bundled = _bundled_helper()
    if bundled is not None:
        return bundled
    sources = [ROOT / "native" / "sck_helper.m", ROOT / "native" / "sck_capture.m"]
    HELPER.parent.mkdir(parents=True, exist_ok=True)
    newest = max(path.stat().st_mtime for path in sources)
    if HELPER.exists() and HELPER.stat().st_mtime >= newest:
        return HELPER
    subprocess.run(
        [
            "clang",
            "-fobjc-arc",
            "-O2",
            *[str(path) for path in sources],
            "-framework",
            "AppKit",
            "-framework",
            "Foundation",
            "-framework",
            "ScreenCaptureKit",
            "-framework",
            "CoreMedia",
            "-framework",
            "CoreVideo",
            "-o",
            str(HELPER),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return HELPER


def display_list() -> list[tuple[int, int, int]]:
    core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    core.CGGetActiveDisplayList.restype = ctypes.c_int32
    core.CGGetActiveDisplayList.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    core.CGDisplayPixelsWide.restype = ctypes.c_size_t
    core.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    core.CGDisplayPixelsHigh.restype = ctypes.c_size_t
    core.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
    needed = ctypes.c_uint32(0)
    core.CGGetActiveDisplayList(0, None, ctypes.byref(needed))
    count = needed.value
    if count == 0:
        return []
    ids = (ctypes.c_uint32 * count)()
    core.CGGetActiveDisplayList(count, ids, ctypes.byref(needed))
    found = []
    for index in range(needed.value):
        display_id = int(ids[index])
        found.append(
            (
                display_id,
                int(core.CGDisplayPixelsWide(display_id)),
                int(core.CGDisplayPixelsHigh(display_id)),
            )
        )
    return found


LIBRARY = ROOT / "build" / "libsck.dylib"
_LIBRARY: ctypes.CDLL | None = None


def ensure_library() -> ctypes.CDLL:
    """Библиотека захвата, загруженная в процесс Hyperion.app."""
    global _LIBRARY
    if _LIBRARY is not None:
        return _LIBRARY
    sources = [ROOT / "native" / "sck_capture.m", ROOT / "native" / "sck_session.m"]
    LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    newest = max(path.stat().st_mtime for path in sources)
    if not LIBRARY.exists() or LIBRARY.stat().st_mtime < newest:
        subprocess.run(
            [
                "clang",
                "-fobjc-arc",
                "-dynamiclib",
                "-O2",
                *[str(path) for path in sources],
                "-framework",
                "AppKit",
                "-framework",
                "Foundation",
                "-framework",
                "ScreenCaptureKit",
                "-framework",
                "CoreMedia",
                "-framework",
                "CoreVideo",
                "-o",
                str(LIBRARY),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    library = ctypes.CDLL(str(LIBRARY))
    library.sck_session_start.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.sck_session_start.restype = ctypes.c_int
    library.sck_session_stop.argtypes = []
    library.sck_session_stop.restype = None
    library.sck_preflight.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.sck_preflight.restype = ctypes.c_int
    library.sck_request_access.argtypes = []
    library.sck_request_access.restype = ctypes.c_int
    _LIBRARY = library
    return library


def main_display() -> int:
    core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    core.CGMainDisplayID.restype = ctypes.c_uint32
    return int(core.CGMainDisplayID())


def _objc():
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def _msg(objc, restype, *argtypes):
    send = objc.objc_msgSend
    send.restype = restype
    send.argtypes = list(argtypes)
    return send


def _frontmost() -> bool:
    """macOS записывает приложение в список записи экрана только если оно на переднем плане."""
    objc = _objc()
    sel = objc.sel_registerName
    app = _msg(objc, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        objc.objc_getClass(b"NSApplication"), sel(b"sharedApplication")
    )
    _msg(objc, ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(
        app, sel(b"setActivationPolicy:"), 0
    )
    _msg(objc, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(app, sel(b"activate"))
    _msg(objc, None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(
        app, sel(b"activateIgnoringOtherApps:"), True
    )
    windows = _msg(objc, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(app, sel(b"windows"))
    count = int(_msg(objc, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(windows, sel(b"count")))
    for index in range(count):
        window = _msg(objc, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(
            windows, sel(b"objectAtIndex:"), index
        )
        _msg(objc, None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            window, sel(b"makeKeyAndOrderFront:"), None
        )
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    mode = ctypes.c_void_p.in_dll(core, "kCFRunLoopDefaultMode")
    core.CFRunLoopRunInMode.restype = ctypes.c_int32
    core.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
    core.CFRunLoopRunInMode(mode, 0.35, False)
    return bool(_msg(objc, ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(app, sel(b"isActive")))


def request_screen_access() -> bool:
    """Системный запрос записи экрана. Вызывать с главного потока, пока окно Hyperion впереди."""
    try:
        _frontmost()
        library = ensure_library()
        if int(library.sck_request_access()):
            return True
        error = ctypes.create_string_buffer(512)
        return int(library.sck_preflight(error, len(error))) == 0
    except Exception:
        return False


def open_screen_settings() -> None:
    subprocess.Popen(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"]
    )


def fit_rgb(frame: np.ndarray, max_edge: int = 200) -> np.ndarray:
    """Уменьшает кадр, сохраняя пропорции. Hyperion сам раскладывает его по диодам."""
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if height < 1 or width < 1:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    long_edge = max(height, width)
    view = frame[:, :, :3]
    if long_edge <= max_edge:
        return np.ascontiguousarray(view)
    step = long_edge / max_edge
    rows = np.minimum(np.arange(0, height, step, dtype=np.float64).astype(np.int32), height - 1)
    cols = np.minimum(np.arange(0, width, step, dtype=np.float64).astype(np.int32), width - 1)
    if len(rows) < 1 or len(cols) < 1:
        return np.ascontiguousarray(view[:1, :1])
    return np.ascontiguousarray(view[rows][:, cols])


def frame_packet(frame: np.ndarray, max_edge: int = 200) -> tuple[bytes, int, int]:
    small = fit_rgb(frame, max_edge)
    height, width = int(small.shape[0]), int(small.shape[1])
    return small.tobytes(), width, height


def horizontal_row(
    frame: np.ndarray, count: int = 27, bottom: float = 0.2, flip: bool = True
) -> bytes:
    """Нижние 20% экрана, основной цвет столбца. Цепочка подключена справа налево."""
    count = max(1, int(count))
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if height < 1 or width < 1:
        return bytes(count * 3)
    band = max(1, min(height, int(height * bottom + 0.999)))
    view = frame[height - band :, :, :3]
    if width < count:
        color = _punch(np.rint(np.median(view.reshape(-1, 3), axis=0)).astype(np.uint8))
        return np.ascontiguousarray(np.tile(color, count)).tobytes()
    block = width // count
    view = view[:, : block * count]
    chunks = view.reshape(band, count, block, 3)
    colors = np.rint(np.median(chunks.reshape(band * block, count, 3), axis=0)).astype(np.uint8)
    colors = np.stack([_punch(color) for color in colors])
    if flip:
        colors = colors[::-1]
    return np.ascontiguousarray(colors).tobytes()


def _punch(color: np.ndarray) -> np.ndarray:
    """Hyperion высветляет тени: слабый красный становится розовым, тёмный чат — белым."""
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(red, green, blue)
    floor = min(red, green, blue)
    if peak < 42:
        return np.zeros(3, dtype=np.uint8)
    lead = (red, green, blue).index(peak)
    if peak >= floor * 2 + 25:
        out = np.zeros(3, dtype=np.uint8)
        out[lead] = np.uint8(255 if peak >= 50 else peak)
        return out
    if peak >= 230 and peak - floor < 30:
        return np.full(3, 255, dtype=np.uint8)
    return np.array((red, green, blue), dtype=np.uint8)


def _tone(color: np.ndarray) -> np.ndarray:
    """Тёмный серый гаснет, иначе Hyperion делает его белым. Красный край остаётся красным."""
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(red, green, blue)
    floor = min(red, green, blue)
    if peak < 24:
        return np.zeros(3, dtype=np.uint8)
    if peak - floor < 16 and peak < 180:
        return np.zeros(3, dtype=np.uint8)
    lead = (red, green, blue).index(peak)
    if peak > floor and peak >= floor * 2 + 12 and peak >= 24:
        out = np.zeros(3, dtype=np.uint8)
        out[lead] = np.uint8(255 if peak >= 32 else peak)
        return out
    if peak >= 220 and peak - floor < 28:
        return np.full(3, 255, dtype=np.uint8)
    return np.array((red, green, blue), dtype=np.uint8)


def _reduce(view: np.ndarray, count: int, across: str) -> np.ndarray:
    count = int(count)
    if count < 1:
        return np.zeros((0, 3), dtype=np.uint8)
    height, width = int(view.shape[0]), int(view.shape[1])
    if height < 1 or width < 1:
        return np.zeros((count, 3), dtype=np.uint8)
    if across == "x":
        if width < count:
            color = _tone(np.rint(np.median(view.reshape(-1, 3), axis=0)).astype(np.uint8))
            return np.tile(color, (count, 1))
        block = width // count
        cropped = view[:, : block * count]
        chunks = cropped.reshape(height, count, block, 3)
        colors = np.rint(np.median(chunks, axis=(0, 2))).astype(np.uint8)
    else:
        if height < count:
            color = _tone(np.rint(np.median(view.reshape(-1, 3), axis=0)).astype(np.uint8))
            return np.tile(color, (count, 1))
        block = height // count
        cropped = view[: block * count]
        chunks = cropped.reshape(count, block, width, 3)
        colors = np.rint(np.median(chunks.reshape(count, block * width, 3), axis=1)).astype(np.uint8)
    return np.stack([_tone(color) for color in colors])


def _as_seen(color: np.ndarray) -> np.ndarray:
    """Красный на экране остаётся красным на ленте. Серый и белый не трогаем."""
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(red, green, blue)
    if peak < 16 or peak - min(red, green, blue) < 28:
        return np.array((red, green, blue), dtype=np.uint8)
    channels = (red, green, blue)
    lead = channels.index(peak)
    second = max(channels[index] for index in range(3) if index != lead)
    if peak < second * 2 + 8:
        return np.array((red, green, blue), dtype=np.uint8)
    out = np.zeros(3, dtype=np.uint8)
    out[lead] = np.uint8(peak)
    return out


def _dim_shadows(color: np.ndarray) -> np.ndarray:
    """Тёмное окно светит тускло. Яркий белый и чистый цвет не прижимаются."""
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(red, green, blue)
    if peak < 12 or peak >= 160:
        return np.array((red, green, blue), dtype=np.uint8)
    level = int(round(peak * peak / 255.0))
    level = min(peak, max(6, level))
    scale = level / peak
    return np.array(
        [int(round(channel * scale)) for channel in (red, green, blue)],
        dtype=np.uint8,
    )


def _natural(color: np.ndarray) -> np.ndarray:
    """Красный остаётся красным. Тёмный и серый столбец гасит диод, иначе он светится розовым."""
    red, green, blue = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(red, green, blue)
    floor = min(red, green, blue)
    if peak < 46:
        return np.zeros(3, dtype=np.uint8)
    if peak - floor < 18:
        if peak >= 200:
            return np.full(3, 255, dtype=np.uint8)
        if peak < 120:
            return np.zeros(3, dtype=np.uint8)
        return np.full(3, peak, dtype=np.uint8)
    # Белая вуаль дока делает красный розовым. Снимаем её и гасим лишний синий.
    hue_red = red - floor
    hue_green = green - floor
    hue_blue = blue - floor
    if max(hue_red, hue_green, hue_blue) < 22:
        return np.zeros(3, dtype=np.uint8)
    if hue_red >= hue_green and hue_red >= hue_blue and hue_red > hue_blue:
        # Лишний синий при ведущем красном — это розовый. Оранжевый, где синего нет, остаётся.
        if hue_blue > hue_green or (hue_green * 4 < hue_red and hue_blue * 4 < hue_red):
            return np.array((hue_red, 0, 0), dtype=np.uint8)
    return np.array((hue_red, hue_green, hue_blue), dtype=np.uint8)


def _without_glare(samples: np.ndarray) -> np.ndarray:
    """Медиана без белых бликов. Белая точка не осветляет соседний тёмный цвет."""
    flat = samples.reshape(-1, 3).astype(np.int16)
    count = int(flat.shape[0])
    if count < 1:
        return np.zeros(3, dtype=np.uint8)
    peak = flat.max(axis=1)
    floor = flat.min(axis=1)
    glare = (peak >= 170) & (peak - floor <= 36)
    kept = flat[~glare]
    if int(kept.shape[0]) < max(1, count // 5):
        kept = flat
    return np.rint(np.median(kept, axis=0)).astype(np.uint8)


def _main_color(view: np.ndarray, count: int, natural: bool = False) -> np.ndarray:
    """Цвет столбца. Белые точки не входят в расчёт и не делают красный розовым."""
    count = int(count)
    if count < 1:
        return np.zeros((0, 3), dtype=np.uint8)
    height, width = int(view.shape[0]), int(view.shape[1])
    if height < 1 or width < 1:
        return np.zeros((count, 3), dtype=np.uint8)
    tone = _natural if natural else lambda color: _dim_shadows(_as_seen(color))
    if width < count:
        picked = _without_glare(view) if natural else np.rint(np.median(view.reshape(-1, 3), axis=0)).astype(np.uint8)
        return np.tile(tone(picked), (count, 1))
    block = width // count
    cropped = view[:, : block * count]
    colors = np.empty((count, 3), dtype=np.uint8)
    for index in range(count):
        samples = cropped[:, index * block : (index + 1) * block]
        if natural:
            picked = _without_glare(samples)
        else:
            picked = np.rint(np.median(samples.reshape(-1, 3), axis=0)).astype(np.uint8)
        colors[index] = tone(picked)
    return colors


def fit_leds(
    frame: np.ndarray,
    bottom: int = 27,
    left: int = 0,
    top: int = 0,
    right: int = 0,
    percent: int = 10,
    span_start: int = 0,
    span_end: int = 100,
    capture_start: int | None = None,
    capture_end: int | None = None,
    natural: bool = False,
) -> bytes:
    """Цвет полосы экрана. Диапазон сжимает картинку на часть диодов, остальные гаснут."""
    bottom = max(0, int(bottom))
    left = max(0, int(left))
    top = max(0, int(top))
    right = max(0, int(right))
    if bottom + left + top + right < 1:
        bottom = 27
    percent = min(100, max(1, int(percent)))
    span_start = min(96, max(0, int(span_start)))
    span_end = min(100, max(span_start + 4, int(span_end)))
    total = bottom + left + top + right
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if height < 1 or width < 1:
        return bytes(total * 3)
    if capture_start is None or capture_end is None:
        band = max(1, min(height, int(height * percent / 100 + 0.999)))
        y0 = height - band
        y1 = height
    else:
        y_start = min(96, max(0, int(capture_start)))
        y_end = min(100, max(y_start + 4, int(capture_end)))
        y0 = int(height * y_start / 100)
        y1 = int(round(height * y_end / 100))
        y0 = max(0, min(height - 1, y0))
        y1 = max(y0 + 1, min(height, y1))
    view = frame[y0:y1, :, :3]
    if total == 1:
        left_at, right_at = 0, 0
    else:
        left_at = int(round(span_start / 100 * (total - 1)))
        right_at = int(round(span_end / 100 * (total - 1)))
    if right_at < left_at:
        right_at = left_at
    active = right_at - left_at + 1
    columns = _main_color(view, active, natural)
    colors = np.zeros((total, 3), dtype=np.uint8)
    for offset, column in enumerate(columns):
        place = total - 1 - (left_at + offset)
        colors[place] = column
    return np.ascontiguousarray(colors).tobytes()


def paint_boxes(
    colors: np.ndarray, boxes: list[tuple[float, float, float, float]]
) -> tuple[bytes, int, int]:
    """Кладёт цвет диода в его прямоугольник, чтобы Hyperion не растягивал одну полоску на весь экран."""
    count = int(colors.shape[0])
    width = max(64, count * 4)
    height = max(36, count * 2)
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for color, box in zip(colors, boxes):
        hmin, hmax, vmin, vmax = box
        x_start = int(np.clip(hmin, 0, 1) * width)
        x_end = int(np.clip(hmax, 0, 1) * width)
        y_start = int(np.clip(vmin, 0, 1) * height)
        y_end = int(np.clip(vmax, 0, 1) * height)
        if x_end <= x_start:
            x_end = min(width, x_start + 1)
        if y_end <= y_start:
            y_end = min(height, y_start + 1)
        image[y_start:y_end, x_start:x_end] = color
    return np.ascontiguousarray(image).tobytes(), width, height


def encode_strip(rgb: bytes, boxes: list[tuple[float, float, float, float]] | None) -> tuple[bytes, int, int]:
    count = len(rgb) // 3
    if count < 1:
        return b"", 1, 1
    if boxes and len(boxes) == count:
        colors = np.frombuffer(rgb, dtype=np.uint8).reshape(count, 3).copy()
        return paint_boxes(colors, boxes)
    return rgb, count, 1


class ScreenStream:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._fd = -1
        self._map: mmap.mmap | None = None
        self._path: Path | None = None
        self._embedded = False
        self.started = False

    def start(self, display_id: int, max_edge: int = 1600, fps: int = 60, embedded: bool = False) -> None:
        self.stop()
        self._embedded = embedded
        path = Path(tempfile.gettempdir()) / f"ampilight-{os.getpid()}.frame"
        if embedded:
            library = ensure_library()
            error = ctypes.create_string_buffer(512)
            code = library.sck_session_start(
                str(path).encode(), int(display_id), int(max_edge), int(fps), error, len(error)
            )
            if code != 0:
                text = error.value.decode("utf-8", "ignore").strip()
                raise RuntimeError(text or "захват экрана не запустился")
            self._path = path
            self._fd = os.open(path, os.O_RDONLY)
            self._map = mmap.mmap(self._fd, MAP_SIZE, access=mmap.ACCESS_READ)
            self._event.clear()
            self.started = True
            return
        proc = subprocess.Popen(
            [str(ensure_helper()), str(path), str(int(display_id)), str(int(max_edge)), str(int(fps))],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._proc = proc
        self._path = path
        deadline = time.monotonic() + 10
        buffered = b""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stderr], [], [], 0.2)
            if proc.poll() is not None and not ready:
                tail = buffered.decode("utf-8", "ignore").strip()
                raise RuntimeError(tail or "захват экрана завершился сразу")
            if not ready:
                continue
            buffered += os.read(proc.stderr.fileno(), 512)
            if b"READY" in buffered:
                break
            if b"ERR" in buffered:
                text = buffered.decode("utf-8", "ignore").strip()
                raise RuntimeError(text.removeprefix("ERR").strip() or "захват экрана не запустился")
        else:
            raise RuntimeError("захват экрана не ответил")
        self._fd = os.open(path, os.O_RDONLY)
        self._map = mmap.mmap(self._fd, MAP_SIZE, access=mmap.ACCESS_READ)
        self.started = True

    def stop(self) -> None:
        proc = self._proc
        embedded = self._embedded
        self.started = False
        self._proc = None
        self._embedded = False
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
        if embedded and _LIBRARY is not None:
            try:
                _LIBRARY.sck_session_stop()
            except Exception:
                pass
        self._event.set()

    def running(self) -> bool:
        proc = self._proc
        if not self.started:
            return False
        return proc is None or proc.poll() is None

    def wake(self) -> None:
        self._event.set()

    def take(self, after_seq: int, timeout: float) -> tuple[int, np.ndarray] | None:
        if self._map is None:
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._event.is_set():
                self._event.clear()
                return None
            frame = self._read_frame(after_seq)
            if frame is not None:
                return frame
            self._event.wait(0.004)
        return None

    def _read_frame(self, after_seq: int) -> tuple[int, np.ndarray] | None:
        mapping = self._map
        if mapping is None:
            return None
        seq = struct.unpack_from("<I", mapping, 0)[0]
        if seq < 2 or seq & 1 or seq == after_seq:
            return None
        width, height, stride = struct.unpack_from("<III", mapping, 4)
        if width < 2 or height < 2 or stride < width * 4:
            return None
        nbytes = stride * height
        if nbytes <= 0 or HEADER + nbytes > MAP_SIZE:
            return None
        raw = np.frombuffer(mapping, dtype=np.uint8, count=nbytes, offset=HEADER).copy()
        if struct.unpack_from("<I", mapping, 0)[0] != seq:
            return None
        view = raw.reshape(height, stride)
        bgra = view[:, : width * 4].reshape(height, width, 4)
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[:, :, 0] = bgra[:, :, 2]
        rgb[:, :, 1] = bgra[:, :, 1]
        rgb[:, :, 2] = bgra[:, :, 0]
        return seq, rgb
