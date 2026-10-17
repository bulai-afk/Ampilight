import numpy as np

from app.detect import (
    ScreenTracker,
    calm_picture,
    crop_screen,
    find_screen,
    grade_picture,
    sample_perimeter,
    trim_edges,
)


def _panel(width=320, height=180) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    frame = np.full((height, width, 3), 22, dtype=np.uint8)
    x0, y0, x1, y1 = 48, 36, 256, 153
    rng = np.random.default_rng(1)
    frame[y0:y1, x0:x1] = rng.integers(30, 240, size=(y1 - y0, x1 - x0, 3), dtype=np.uint8)
    return frame, (x0, y0, x1, y1)


def test_finds_tv_shaped_panel():
    frame, (x0, y0, x1, y1) = _panel()
    rect = find_screen(frame)
    assert rect is not None
    x, y, w, h = rect
    height, width = frame.shape[:2]
    cx = (x + w / 2) * width
    cy = (y + h / 2) * height
    assert x0 < cx < x1
    assert y0 < cy < y1
    assert w > 0.35
    assert h > 0.3


def test_flat_wall_is_not_a_screen():
    frame = np.full((120, 200, 3), 48, dtype=np.uint8)
    assert find_screen(frame) is None


def test_crop_stays_inside_panel():
    frame, (x0, y0, x1, y1) = _panel()
    rect = find_screen(frame)
    crop = crop_screen(frame, rect)
    assert crop is not None
    assert crop.shape[0] < y1 - y0
    assert crop.shape[1] < x1 - x0
    assert float(crop.mean()) > 40


def test_trim_pulls_each_edge_inward():
    framed = trim_edges((0.1, 0.2, 0.8, 0.6), 0.25, 0.25, 0.1, 0.1)
    x, y, w, h = framed
    assert abs(x - 0.3) < 1e-6
    assert abs(y - 0.26) < 1e-6
    assert abs(w - 0.4) < 1e-6
    assert abs(h - 0.48) < 1e-6


def test_calm_picture_keeps_black_black_and_gray_gray():
    black = np.full((8, 8, 3), (12, 36, 48), dtype=np.uint8)
    gray = np.full((8, 8, 3), 150, dtype=np.uint8)
    white = np.full((8, 8, 3), 245, dtype=np.uint8)
    out_black = calm_picture(black)
    out_gray = calm_picture(gray)
    out_white = calm_picture(white)
    assert int(out_black.max()) < 18
    assert int(out_black.max()) - int(out_black.min()) < 10
    assert 60 < float(out_gray.mean()) < 140
    assert float(out_white.mean()) > 200


def test_contrast_pulls_pink_toward_red():
    pink = np.full((4, 4, 3), (200, 150, 150), dtype=np.uint8)
    graded = grade_picture(pink, brightness=1.0, contrast=1.8)
    red, green, blue = (int(graded[0, 0, channel]) for channel in range(3))
    assert red - green > (200 - 150)


def test_mirror_swaps_left_and_right():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, :60] = (40, 40, 40)
    frame[:, 60:] = (200, 30, 30)
    points = ((0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95))
    plain = sample_perimeter(frame, points, 8, 0.1, mirror=False)
    mirrored = sample_perimeter(frame, points, 8, 0.1, mirror=True)
    assert int(plain[0, 0]) < 80
    assert int(mirrored[0, 0]) > 150


def test_explicit_counts_follow_the_top():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:24, :] = (180, 20, 20)
    points = ((0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95))
    colors = sample_perimeter(frame, points, 6, 0.12, counts=(1, 4, 1, 0))
    assert colors.shape == (6, 3)
    assert int(colors[1, 0]) > int(colors[1, 2]) + 40


def test_perimeter_reads_each_edge():
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:24, :] = (180, 20, 20)
    frame[-24:, :] = (20, 20, 180)
    points = ((0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95))
    colors = sample_perimeter(frame, points, 8, 0.12)
    assert colors.shape == (8, 3)
    # После левого края идут диоды верхней стороны — красные.
    assert int(colors[2, 0]) > int(colors[2, 2]) + 40
    # Нижняя сторона — синяя.
    assert int(colors[6, 2]) > int(colors[6, 0]) + 40


def test_tracker_holds_screen_through_a_dark_frame():
    frame, _box = _panel()
    tracker = ScreenTracker()
    assert tracker.update(frame) is not None
    dark = np.full_like(frame, 8)
    assert tracker.update(dark) is not None
