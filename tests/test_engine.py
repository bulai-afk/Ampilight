import numpy as np

from app.engine import compose_pixels, majority_columns, pack_colors


def test_solid_red_matches_script_packet():
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    frame[:] = (255, 0, 0)
    _grid, pixels = compose_pixels(
        frame,
        rows=2,
        cols=4,
        mode="strip",
        reverse=True,
        serpentine=False,
        repeat=1,
        red_gain=1,
        green_gain=1,
        blue_gain=1,
        brightness=100,
    )
    assert pixels.shape == (4, 3)
    assert np.all(pixels == (255, 0, 0))
    packet = pack_colors(pixels)
    assert packet.startswith(b"D")
    assert len(packet) == 1 + 4 * 3


def test_reverse_swaps_columns():
    frame = np.zeros((20, 40, 3), dtype=np.uint8)
    frame[:, :20] = (255, 0, 0)
    frame[:, 20:] = (0, 0, 255)
    _grid, pixels = compose_pixels(
        frame,
        rows=1,
        cols=2,
        mode="strip",
        reverse=True,
        serpentine=False,
        repeat=1,
        red_gain=1,
        green_gain=1,
        blue_gain=1,
        brightness=100,
    )
    assert tuple(int(v) for v in pixels[0]) == (0, 0, 255)
    assert tuple(int(v) for v in pixels[1]) == (255, 0, 0)


def test_majority_ignores_a_lone_color():
    grid = np.zeros((5, 1, 3), dtype=np.uint8)
    grid[:4, 0] = (200, 10, 10)
    grid[4, 0] = (0, 0, 255)
    out = majority_columns(grid)
    assert abs(int(out[0, 0]) - 200) <= 1
    assert int(out[0, 2]) < 40


def test_grid_serpentine_order():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    frame[:10, :10] = (255, 0, 0)
    frame[:10, 10:] = (0, 255, 0)
    frame[10:, :10] = (0, 0, 255)
    frame[10:, 10:] = (255, 255, 255)
    _grid, pixels = compose_pixels(
        frame,
        rows=2,
        cols=2,
        mode="grid",
        reverse=False,
        serpentine=True,
        repeat=1,
        red_gain=1,
        green_gain=1,
        blue_gain=1,
        brightness=100,
    )
    assert [tuple(int(v) for v in row) for row in pixels] == [
        (255, 0, 0),
        (0, 255, 0),
        (255, 255, 255),
        (0, 0, 255),
    ]


def test_repeat_and_brightness():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:] = (255, 0, 0)
    _grid, pixels = compose_pixels(
        frame,
        rows=1,
        cols=1,
        mode="strip",
        reverse=False,
        serpentine=False,
        repeat=3,
        red_gain=1,
        green_gain=1,
        blue_gain=1,
        brightness=50,
    )
    assert len(pixels) == 3
    assert int(pixels[0, 0]) == 128
    assert int(pixels[0, 1]) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
