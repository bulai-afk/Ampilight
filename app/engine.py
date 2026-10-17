"""Цвета экрана: медиана клетки, затем самый частый оттенок столбца.

Так устроен рабочий скрипт: оттенок квантуется шагом 40, берётся самая большая группа,
и уже по ней считается медиана.
"""

from __future__ import annotations

import numpy as np

BIN_SIZE = 40
SAMPLES = 8


class GridSampler:
    """Кэширует координаты клеток, пока размер кадра и сетка не изменились."""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._ys: np.ndarray | None = None
        self._xs: np.ndarray | None = None

    def grid(self, frame: np.ndarray, rows: int, cols: int, samples: int = SAMPLES) -> np.ndarray:
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        samples = max(2, int(samples))
        height, width, _ = frame.shape
        key = (height, width, rows, cols, samples)
        if key != self._key:
            self._ys, self._xs = _cell_indices(height, width, rows, cols, samples)
            self._key = key
        picked = frame[self._ys, self._xs]
        median = np.median(picked, axis=(2, 3))
        return np.clip(np.rint(median), 0, 255).astype(np.uint8)


def _cell_indices(
    height: int, width: int, rows: int, cols: int, samples: int
) -> tuple[np.ndarray, np.ndarray]:
    y_edges = np.linspace(0, height, rows + 1).astype(np.int32)
    x_edges = np.linspace(0, width, cols + 1).astype(np.int32)
    y_idx = np.zeros((rows, samples), dtype=np.int32)
    x_idx = np.zeros((cols, samples), dtype=np.int32)
    for row in range(rows):
        start = int(y_edges[row])
        end = max(start + 1, int(y_edges[row + 1]))
        y_idx[row] = np.linspace(start, end - 1, samples).astype(np.int32)
    for col in range(cols):
        start = int(x_edges[col])
        end = max(start + 1, int(x_edges[col + 1]))
        x_idx[col] = np.linspace(start, end - 1, samples).astype(np.int32)
    ys = np.broadcast_to(y_idx[:, None, :, None], (rows, cols, samples, samples))
    xs = np.broadcast_to(x_idx[None, :, None, :], (rows, cols, samples, samples))
    return np.ascontiguousarray(ys), np.ascontiguousarray(xs)


def majority_columns(grid: np.ndarray, bin_size: int = BIN_SIZE) -> np.ndarray:
    """Один цвет на столбец: медиана самой частой группы оттенков."""
    row_count, col_count, _ = grid.shape
    out = np.zeros((col_count, 3), dtype=np.uint8)
    if row_count == 0 or col_count == 0:
        return out
    step = bin_size if bin_size > 0 else BIN_SIZE
    for col in range(col_count):
        cells = grid[:, col, :].astype(np.float32)
        quantized = (cells // step).astype(np.int32)
        _bins, inverse, counts = np.unique(
            quantized, axis=0, return_inverse=True, return_counts=True
        )
        chosen = cells[inverse == int(np.argmax(counts))]
        out[col] = np.clip(np.rint(np.median(chosen, axis=0)), 0, 255)
    return out


def compose_pixels(
    frame: np.ndarray,
    *,
    rows: int,
    cols: int,
    mode: str,
    reverse: bool,
    serpentine: bool,
    repeat: int,
    red_gain: float,
    green_gain: float,
    blue_gain: float,
    brightness: float,
    sampler: GridSampler | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Возвращает сетку клеток и итоговые цвета диодов."""
    sampler = sampler or GridSampler()
    grid = sampler.grid(frame, rows, cols)
    if mode == "grid":
        ordered = grid.copy()
        if serpentine:
            ordered[1::2] = ordered[1::2, ::-1]
        pixels = ordered.reshape(-1, 3)
    else:
        pixels = majority_columns(grid)
    if reverse:
        pixels = pixels[::-1].copy()
    pixels = apply_gain(pixels, red_gain, green_gain, blue_gain, brightness)
    times = max(1, int(repeat))
    if times > 1:
        pixels = np.repeat(pixels, times, axis=0)
    return grid, pixels


def apply_gain(
    pixels: np.ndarray,
    red_gain: float,
    green_gain: float,
    blue_gain: float,
    brightness: float,
) -> np.ndarray:
    scale = np.array([red_gain, green_gain, blue_gain], dtype=np.float32) * (
        float(brightness) / 100.0
    )
    mixed = pixels.astype(np.float32) * scale
    return np.clip(np.rint(mixed), 0, 255).astype(np.uint8)


def blend(previous: np.ndarray | None, current: np.ndarray, keep: float) -> np.ndarray:
    """keep — доля прошлого кадра, 0 оставляет цвет как есть."""
    if previous is None or previous.shape != current.shape or keep <= 0:
        return current
    weight = float(np.clip(keep, 0.0, 0.92))
    mixed = previous.astype(np.float32) * weight + current.astype(np.float32) * (1.0 - weight)
    return np.clip(np.rint(mixed), 0, 255).astype(np.uint8)


def pack_colors(pixels: np.ndarray) -> bytes:
    flat = np.ascontiguousarray(pixels, dtype=np.uint8)
    return b"D" + flat.tobytes()


def output_length(mode: str, cols: int, rows: int, repeat: int) -> int:
    base = max(1, int(cols)) if mode != "grid" else max(1, int(cols)) * max(1, int(rows))
    return base * max(1, int(repeat))
