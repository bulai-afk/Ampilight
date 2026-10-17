"""Ищет прямоугольник экрана в кадре камеры.

Экран — это яркое пятно с резкой кромкой и пропорциями телевизора.
Плоская стена такого контура не даёт.
"""

from __future__ import annotations

import math

import numpy as np

Rect = tuple[float, float, float, float]


def find_screen(frame: np.ndarray) -> Rect | None:
    """Нормализованный прямоугольник (x, y, ширина, высота) или None."""
    if frame.ndim != 3 or frame.shape[0] < 24 or frame.shape[1] < 24:
        return None
    step = max(1, int(round(frame.shape[1] / 48)))
    small = frame[::step, ::step]
    gray = small.astype(np.float32).mean(axis=2)
    height, width = gray.shape
    if height < 12 or width < 12:
        return None
    mag = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1])) + np.abs(
        np.diff(gray, axis=0, prepend=gray[:1, :])
    )
    mag[0, :] = 0
    mag[:, 0] = 0
    luma_table = _table(gray)
    edge_table = _table(mag)

    best: tuple[float, int, int, int, int] | None = None
    min_side = 0.22
    y_stops = range(0, int(height * 0.55), 4)
    x_stops = range(0, int(width * 0.55), 4)
    for y0 in y_stops:
        for x0 in x_stops:
            y_start = y0 + max(4, int(height * min_side))
            for y1 in range(y_start, height + 1, 4):
                x_start = x0 + max(4, int(width * min_side))
                for x1 in range(x_start, width + 1, 4):
                    score = _score(
                        luma_table,
                        edge_table,
                        width,
                        height,
                        y0,
                        x0,
                        y1,
                        x1,
                    )
                    if score is None:
                        continue
                    if best is None or score > best[0]:
                        best = (score, x0, y0, x1 - x0, y1 - y0)
    if best is not None:
        _score_value, x, y, rect_w, rect_h = best
        return (x / width, y / height, rect_w / width, rect_h / height)
    return _bright_region(gray)


def trim_edges(
    rect: Rect,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> Rect:
    """Сдвигает границы внутрь. Доли задаются от ширины и высоты прямоугольника."""
    x, y, width, height = rect
    left = float(np.clip(left, 0.0, 0.45))
    right = float(np.clip(right, 0.0, 0.45))
    top = float(np.clip(top, 0.0, 0.45))
    bottom = float(np.clip(bottom, 0.0, 0.45))
    if left + right > 0.9:
        scale = 0.9 / (left + right)
        left *= scale
        right *= scale
    if top + bottom > 0.9:
        scale = 0.9 / (top + bottom)
        top *= scale
        bottom *= scale
    return (
        x + width * left,
        y + height * top,
        width * (1.0 - left - right),
        height * (1.0 - top - bottom),
    )


def calm_picture(frame: np.ndarray) -> np.ndarray:
    """Камера засвечивает кадр: в чёрном остаётся голубой, серый уходит в белый."""
    pixels = frame.astype(np.float32)
    luma = pixels.mean(axis=2, keepdims=True)
    saturation = np.clip((luma - 8.0) / 40.0, 0.0, 1.0)
    pixels = luma + (pixels - luma) * saturation
    shaped = np.clip((pixels - 32.0) / (255.0 - 32.0), 0.0, 1.0)
    shaped = np.power(shaped, 1.55)
    return np.clip(np.rint(shaped * 255.0), 0, 255).astype(np.uint8)


def grade_picture(frame: np.ndarray, brightness: float = 1.0, contrast: float = 1.0) -> np.ndarray:
    """Яркость и контраст вокруг серого. Контраст поднимает тусклый красный из розового."""
    pixels = frame.astype(np.float32)
    contrast = float(np.clip(contrast, 0.2, 3.0))
    brightness = float(np.clip(brightness, 0.2, 3.0))
    pixels = (pixels - 128.0) * contrast + 128.0
    pixels *= brightness
    return np.clip(np.rint(pixels), 0, 255).astype(np.uint8)


def sample_perimeter(
    frame: np.ndarray,
    points: tuple[tuple[float, float], ...],
    count: int,
    depth: float,
    mirror: bool = False,
    counts: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Цвет полосы у каждого края четырёхугольника, по кругу от нижнего левого угла.

    Точки: левый верх, правый верх, правый низ, левый низ, в долях кадра.
    counts — сколько диодов слева, сверху, справа и снизу. Без него число делится по длине сторон.
    Глубина — доля пути от края к центру, как «40% от края» на телевизоре.
    """
    height, width = frame.shape[:2]
    count = max(1, int(count))
    depth = float(np.clip(depth, 0.02, 0.5))
    corners = np.array(points, dtype=np.float32).reshape(4, 2)
    corners[:, 0] = np.clip(corners[:, 0], 0.0, 1.0) * max(1, width - 1)
    corners[:, 1] = np.clip(corners[:, 1], 0.0, 1.0) * max(1, height - 1)
    # По часовой от нижнего левого: левый край вверх, верх вправо, правый вниз, низ влево.
    order = (3, 0, 1, 2)
    edges = []
    lengths = []
    for index in range(4):
        start = corners[order[index]]
        end = corners[order[(index + 1) % 4]]
        edges.append((start, end))
        lengths.append(float(np.linalg.norm(end - start)))
    if counts is None:
        counts = _edge_counts(lengths, count)
    else:
        counts = [max(0, int(item)) for item in counts]
        count = max(1, sum(counts))
    centroid = corners.mean(axis=0)
    colors = np.zeros((count, 3), dtype=np.float32)
    placed = 0
    for (start, end), leds in zip(edges, counts):
        for led in range(leds):
            if placed >= count:
                break
            point = start * (1.0 - (led + 0.5) / leds) + end * ((led + 0.5) / leds)
            inward = centroid - point
            reach = float(np.linalg.norm(inward))
            if reach < 1.0:
                inward = np.array([0.0, 0.0], dtype=np.float32)
            else:
                inward = inward / reach
            samples = np.zeros(3, dtype=np.float32)
            steps = 4
            for step in range(steps):
                spot = point + inward * reach * depth * ((step + 0.5) / steps)
                x = int(np.clip(round(float(spot[0])), 0, width - 1))
                y = int(np.clip(round(float(spot[1])), 0, height - 1))
                samples += frame[y, x]
            colors[placed] = samples / steps
            placed += 1
    colors = np.clip(np.rint(colors), 0, 255).astype(np.uint8)
    if mirror:
        colors = _mirror_perimeter(colors, counts)
    return colors


def _mirror_perimeter(colors: np.ndarray, counts: list[int]) -> np.ndarray:
    """Левый и правый края меняются местами: камера показывает кадр зеркально."""
    left_n, top_n, right_n, bottom_n = counts
    index = 0
    left = colors[index : index + left_n]
    index += left_n
    top = colors[index : index + top_n]
    index += top_n
    right = colors[index : index + right_n]
    index += right_n
    bottom = colors[index : index + bottom_n]
    return np.concatenate(
        [right[::-1], top[::-1], left[::-1], bottom[::-1]],
        axis=0,
    )


def _edge_counts(lengths: list[float], count: int) -> list[int]:
    weights = np.array(lengths, dtype=np.float64)
    total = float(weights.sum())
    if total <= 0:
        weights[:] = 1.0
        total = 4.0
    raw = weights / total * count
    counts = np.floor(raw).astype(int)
    leftover = count - int(counts.sum())
    order = np.argsort(-(raw - counts))
    for index in range(leftover):
        counts[int(order[index % 4])] += 1
    return [int(item) for item in counts]


def crop_screen(frame: np.ndarray, rect: Rect, inset: float = 0.06) -> np.ndarray | None:
    """Вырезает найденный экран и чуть отступает от рамки."""
    height, width = frame.shape[:2]
    x, y, rect_w, rect_h = rect
    x += rect_w * inset
    y += rect_h * inset
    rect_w *= 1 - 2 * inset
    rect_h *= 1 - 2 * inset
    x0 = int(np.clip(round(x * width), 0, width - 2))
    y0 = int(np.clip(round(y * height), 0, height - 2))
    x1 = int(np.clip(round((x + rect_w) * width), x0 + 2, width))
    y1 = int(np.clip(round((y + rect_h) * height), y0 + 2, height))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return frame[y0:y1, x0:x1]


class ScreenTracker:
    """Держит прямоугольник, если экран на миг погас или поиск пропустил кадр."""

    def __init__(self) -> None:
        self.rect: Rect | None = None
        self.miss = 0

    def reset(self) -> None:
        self.rect = None
        self.miss = 0

    def update(self, frame: np.ndarray) -> Rect | None:
        found = find_screen(frame)
        if found is None:
            self.miss += 1
            if self.miss > 8:
                self.rect = None
            return self.rect
        self.miss = 0
        if self.rect is None:
            self.rect = found
            return self.rect
        self.rect = tuple(
            previous * 0.7 + current * 0.3 for previous, current in zip(self.rect, found)
        )
        return self.rect


def _bright_region(gray: np.ndarray) -> Rect | None:
    """Прямоугольник вокруг яркого пятна, если у него пропорции экрана."""
    height, width = gray.shape
    level = float(np.percentile(gray, 78))
    if level < 36:
        return None
    mask = gray >= level
    fraction = float(mask.mean())
    if fraction < 0.08 or fraction > 0.9:
        return None
    rows, cols = np.nonzero(mask)
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    rect_h = y1 - y0
    rect_w = x1 - x0
    if rect_w * rect_h < 0.1 * height * width:
        return None
    aspect = rect_w / max(1, rect_h)
    if not (1.1 <= aspect <= 2.6 or 0.38 <= aspect <= 0.9):
        return None
    return (x0 / width, y0 / height, rect_w / width, rect_h / height)


def _table(values: np.ndarray) -> np.ndarray:
    table = np.zeros((values.shape[0] + 1, values.shape[1] + 1), dtype=np.float32)
    table[1:, 1:] = np.cumsum(np.cumsum(values, axis=0), axis=1)
    return table


def _area(table: np.ndarray, y0: int, x0: int, y1: int, x1: int) -> float:
    return float(table[y1, x1] - table[y0, x1] - table[y1, x0] + table[y0, x0])


def _score(
    luma_table: np.ndarray,
    edge_table: np.ndarray,
    width: int,
    height: int,
    y0: int,
    x0: int,
    y1: int,
    x1: int,
) -> float | None:
    rect_w = x1 - x0
    rect_h = y1 - y0
    aspect = rect_w / rect_h
    landscape = 1.15 <= aspect <= 2.55
    portrait = 0.39 <= aspect <= 0.87
    if not landscape and not portrait:
        return None
    if rect_w * rect_h < 0.08 * width * height:
        return None
    thickness = 2
    if rect_w <= thickness * 2 + 2 or rect_h <= thickness * 2 + 2:
        return None
    outer_edge = _area(edge_table, y0, x0, y1, x1)
    inner_edge = _area(edge_table, y0 + thickness, x0 + thickness, y1 - thickness, x1 - thickness)
    border_n = rect_w * rect_h - (rect_w - 2 * thickness) * (rect_h - 2 * thickness)
    density = (outer_edge - inner_edge) / border_n
    inner_luma = _area(luma_table, y0 + thickness, x0 + thickness, y1 - thickness, x1 - thickness)
    inner_n = (rect_w - 2 * thickness) * (rect_h - 2 * thickness)
    inside = inner_luma / inner_n
    pad = 3
    sx0 = max(0, x0 - pad)
    sy0 = max(0, y0 - pad)
    sx1 = min(width, x1 + pad)
    sy1 = min(height, y1 + pad)
    ring_sum = _area(luma_table, sy0, sx0, sy1, sx1) - _area(luma_table, y0, x0, y1, x1)
    ring_n = (sx1 - sx0) * (sy1 - sy0) - rect_w * rect_h
    outside = ring_sum / ring_n if ring_n > 0 else inside
    brighter = inside - outside
    # Слабый край и почти та же яркость — это виньетка камеры или стена, не экран.
    if inside < 42 or (density < 10 and brighter < 26):
        return None
    target = 1.78 if landscape else 1 / 1.78
    aspect_score = math.exp(-((aspect - target) ** 2) / 0.28)
    area_score = math.sqrt((rect_w * rect_h) / (width * height))
    return (density + max(0.0, brighter) * 0.35) * aspect_score * (0.3 + area_score)
