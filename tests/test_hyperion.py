import base64
import json
import socket
import threading

import numpy as np

from app.hyperion import DEFAULT_PRIORITY, SCREEN_MODE, HyperionClient, _led_boxes, live_state, screen_hold
from app.sck import encode_strip, fit_leds, fit_rgb, horizontal_row


def _serve(script: list[dict]) -> tuple[int, list[dict], threading.Thread]:
    seen: list[dict] = []
    ready = threading.Event()
    holder: list[int] = []

    def run() -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        holder.append(server.getsockname()[1])
        ready.set()
        server.settimeout(4)
        try:
            conn, _addr = server.accept()
        except TimeoutError:
            server.close()
            return
        conn.settimeout(3)
        buffer = b""
        try:
            while len(seen) < len(script):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer and len(seen) < len(script):
                    raw, _, buffer = buffer.partition(b"\n")
                    command = json.loads(raw)
                    seen.append(command)
                    reply = script[len(seen) - 1]
                    conn.sendall((json.dumps(reply) + "\n").encode())
        except TimeoutError:
            pass
        finally:
            conn.close()
            server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(2)
    return holder[0], seen, thread


def test_static_color_uses_hyperion_json():
    port, seen, thread = _serve(
        [
            {"success": True},
            {
                "success": True,
                "info": {"instances": [{"instance": 1, "friendly_name": "Стол", "running": True}]},
            },
            {"success": True},
            {"success": True},
            {"success": True},
        ]
    )
    client = HyperionClient()
    try:
        assert client.connect("127.0.0.1", port, "hyperion") == [(1, "Стол")]
        client.set_color((10, 20, 30), priority=20)
        client.clear(20)
    finally:
        client.close()
        thread.join(2)

    assert [item["command"] for item in seen] == [
        "authorize",
        "serverinfo",
        "instance",
        "color",
        "clear",
    ]
    assert seen[0]["password"] == "hyperion"
    assert seen[2]["subcommand"] == "startInstance"
    assert seen[2]["instance"] == 1
    assert seen[3]["color"] == [10, 20, 30]
    assert seen[3]["priority"] == 20
    assert seen[3]["instance"] == [1]
    assert seen[3]["duration"] == -1
    assert seen[4]["priority"] == 20


def test_live_state_reads_the_visible_source():
    info = {
        "success": True,
        "info": {
            "components": [
                {"name": "ALL", "enabled": True},
                {"name": "LEDDEVICE", "enabled": True},
            ],
            "priorities_autoselect": False,
            "priorities": [
                {
                    "priority": 1,
                    "visible": True,
                    "active": True,
                    "componentId": "EFFECT",
                    "origin": "System",
                    "owner": "Fire",
                },
                {
                    "priority": 250,
                    "visible": False,
                    "active": True,
                    "componentId": "GRABBER",
                    "origin": "System",
                    "owner": "dispmanx",
                },
            ],
        },
    }
    state = live_state(info, 1)
    assert state["on"] is True
    assert state["mode"] == "Fire"
    assert state["kind"] == "EFFECT"
    assert state["priority"] == 1
    assert state["manual"] is True
    assert state["rgb"] is None

    info["info"]["priorities"][0] = {
        "priority": 50,
        "visible": True,
        "active": True,
        "componentId": "COLOR",
        "origin": "Ampilight",
        "value": {"RGB": [10, 20, 30], "HSL": [0, 0, 0]},
    }
    color = live_state(info, 1)
    assert color["mode"] == "Solid"
    assert color["rgb"] == (10, 20, 30)

    info["info"]["components"][1]["enabled"] = False
    assert live_state(info, 1)["on"] is False


def test_screen_hold_lets_home_assistant_take_over():
    assert DEFAULT_PRIORITY == 128
    assert SCREEN_MODE == "Адаптив"
    base = {"components": [{"name": "LEDDEVICE", "enabled": True}, {"name": "ALL", "enabled": True}]}
    assert screen_hold({"info": {**base, "priorities": [
        {"priority": 128, "owner": "адаптив", "active": True, "visible": True},
    ]}}) == "ours"
    assert screen_hold({"info": {**base, "priorities": [
        {"priority": 128, "owner": "Warm mood blobs", "active": True, "visible": True},
    ]}}) == "other"
    assert screen_hold({"info": {**base, "priorities": [
        {"priority": 50, "owner": "Home Assistant", "active": True, "visible": True},
        {"priority": 128, "owner": "адаптив", "active": True, "visible": False},
    ]}}) == "cover"
    assert screen_hold({"info": {**base, "priorities": []}}) == "gone"
    assert screen_hold({"info": {**base, "priorities": [
        {"priority": 128, "owner": None, "origin": "адаптив@::ffff:192.168.100.3", "active": True, "visible": True},
    ]}}) == "ours"


def test_screen_image_uses_hyperion_json():
    port, seen, thread = _serve(
        [
            {"success": True},
            {"success": True, "info": {"instances": [{"instance": 1, "friendly_name": "Стол"}]}},
            {"success": True},
            {"success": True},
            {"success": True},
        ]
    )
    client = HyperionClient()
    raw = bytes([1, 2, 3, 4, 5, 6])
    try:
        assert client.connect("127.0.0.1", port, "hyperion") == [(1, "Стол")]
        client.set_image(raw, 2, 1, 20, 1)
        client.set_image(raw, 2, 1, 20, 1)
    finally:
        client.close()
        thread.join(2)

    assert [item["command"] for item in seen] == [
        "authorize",
        "serverinfo",
        "instance",
        "image",
        "image",
    ]
    image = seen[3]
    assert image["imagewidth"] == 2
    assert image["imageheight"] == 1
    assert image["priority"] == 20
    assert image["instance"] == [1]
    assert "format" not in image
    assert image["origin"] == SCREEN_MODE
    assert image["duration"] == -1
    assert base64.b64decode(image["imagedata"]) == raw


def test_stopped_screen_does_not_send():
    port, seen, thread = _serve(
        [
            {"success": True},
            {"success": True, "info": {"instances": [{"instance": 1, "friendly_name": "Стол"}]}},
            {"success": True},
        ]
    )
    client = HyperionClient()
    gate = threading.Event()
    gate.set()
    try:
        client.connect("127.0.0.1", port, "hyperion")
        client.set_image(b"abc", 1, 1, 20, 1, gate)
    finally:
        client.close()
        thread.join(2)
    assert [item["command"] for item in seen] == ["authorize", "serverinfo", "instance"]


def test_horizontal_row_uses_the_bottom_and_flips():
    frame = np.zeros((10, 27, 3), dtype=np.uint8)
    frame[:8, :, 1] = 255
    frame[8:, 0, 0] = 200
    frame[8:, -1, 2] = 90
    row = horizontal_row(frame, 27)
    assert len(row) == 27 * 3
    assert row[0:3] == bytes([0, 0, 255])
    assert row[-3:] == bytes([255, 0, 0])
    assert row[1] == 0


def test_horizontal_row_keeps_red_and_black():
    frame = np.zeros((20, 2, 3), dtype=np.uint8)
    frame[16:, 0] = (64, 2, 16)
    frame[16:, 1] = (29, 25, 25)
    row = horizontal_row(frame, 2, flip=False)
    assert row[:3] == bytes([255, 0, 0])
    assert row[3:] == bytes([0, 0, 0])


def test_horizontal_row_keeps_the_main_color():
    frame = np.zeros((20, 1, 3), dtype=np.uint8)
    frame[16:, 0, 0] = 255
    frame[16, 0] = (255, 255, 255)
    row = horizontal_row(frame, 1, flip=False)
    assert row == bytes([255, 0, 0])


def test_fit_leds_averages_the_bottom_and_starts_at_the_right():
    frame = np.zeros((100, 40, 3), dtype=np.uint8)
    frame[:90, :, 1] = 255
    frame[90:, :20, 2] = 180
    frame[90:, 20:, 0] = 180
    row = fit_leds(frame, bottom=2, percent=10)
    assert row[:3] == bytes([180, 0, 0])
    assert row[3:6] == bytes([0, 0, 180])


def test_fit_leds_keeps_the_average_of_the_bottom():
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[18:, :10] = (90, 8, 8)
    frame[18:, 10:20] = (30, 30, 30)
    frame[18:, 20:] = (90, 8, 8)
    row = fit_leds(frame, bottom=3, percent=10)
    assert row[:3] == bytes([32, 0, 0])
    assert row[3:6] == bytes([6, 6, 6])
    assert row[6:9] == bytes([32, 0, 0])


def test_fit_leds_keeps_burgundy_beside_gray_text():
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[18:, :15] = (80, 24, 36)
    frame[18:, 15:] = (170, 168, 166)
    row = fit_leds(frame, bottom=2, percent=10, natural=True)
    gray = tuple(row[:3])
    burgundy = tuple(row[3:6])
    assert burgundy[0] > burgundy[1] + 8
    assert burgundy[0] > burgundy[2]
    assert abs(gray[0] - gray[1]) < 12
    assert gray[0] > burgundy[0]


def test_fit_leds_natural_ignores_white_glare():
    frame = np.zeros((40, 27, 3), dtype=np.uint8)
    frame[36:, :] = (72, 4, 18)
    frame[36:, ::2] = (250, 250, 250)
    red, green, blue = fit_leds(frame, bottom=1, percent=10, natural=True)[:3]
    assert red > 40
    assert green < 15
    assert blue < 15


def test_fit_leds_natural_keeps_a_dark_area_dark():
    frame = np.zeros((40, 27, 3), dtype=np.uint8)
    frame[36:, :] = (28, 22, 24)
    assert max(fit_leds(frame, bottom=1, percent=10, natural=True)[:3]) < 20


def test_fit_leds_keeps_red_when_white_specks_are_in_the_band():
    frame = np.zeros((20, 40, 3), dtype=np.uint8)
    frame[18:, :, 0] = 255
    frame[18:, :4, 1] = 255
    frame[18:, :4, 2] = 255
    row = fit_leds(frame, bottom=2, percent=10)
    assert row[:3] == bytes([255, 0, 0])
    assert row[3:6] == bytes([255, 0, 0])


def test_fit_leds_range_compresses_onto_the_right_diodes():
    frame = np.zeros((20, 100, 3), dtype=np.uint8)
    frame[18:, :50, 2] = 200
    frame[18:, 50:, 0] = 200
    row = fit_leds(frame, bottom=4, percent=10, span_start=50, span_end=100)
    assert row[:3] == bytes([200, 0, 0])
    assert row[3:6] == bytes([0, 0, 200])
    assert row[6:] == bytes(6)


def test_led_boxes_reads_fractions_and_percents():
    info = {
        "info": {
            "leds": [
                {"hmin": 0, "hmax": 10, "vmin": 90, "vmax": 100},
                {"hmin": 50, "hmax": 60, "vmin": 10, "vmax": 20},
            ]
        }
    }
    assert _led_boxes(info) == [(0.0, 0.1, 0.9, 1.0), (0.5, 0.6, 0.1, 0.2)]


def test_encode_strip_paints_the_first_diode_into_its_box():
    raw = bytes([255, 255, 255, 0, 0, 0])
    image, width, height = encode_strip(raw, [(0.0, 0.5, 0.0, 1.0), (0.5, 1.0, 0.0, 1.0)])
    frame = np.frombuffer(image, dtype=np.uint8).reshape(height, width, 3)
    assert tuple(frame[0, 0]) == (255, 255, 255)
    assert tuple(frame[0, width - 1]) == (0, 0, 0)


def test_fit_rgb_shrinks_the_long_edge():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[:, :, 0] = 255
    small = fit_rgb(frame, 50)
    assert small.shape[1] <= 50
    assert small.shape[0] >= 1
    assert small.shape[2] == 3
    assert int(small[0, 0, 0]) == 255


def test_closed_lid_drops_the_frozen_frame():
    from app.desk_screen import should_drop_capture

    assert should_drop_capture(True, True, 100, 100, 100.2) is True
    assert should_drop_capture(False, True, 100, 100, 100.4) is False
    assert should_drop_capture(False, True, 100, 100, 102) is True
    assert should_drop_capture(False, False, 100, 100, 104) is True
    assert should_drop_capture(False, False, 0, 100, 101) is False


def test_wrong_password_is_refused():
    port, _seen, thread = _serve([{"success": False, "error": "неверный пароль"}])
    client = HyperionClient()
    try:
        try:
            client.connect("127.0.0.1", port, "nope")
        except RuntimeError as exc:
            assert "неверный пароль" in str(exc)
        else:
            raise AssertionError("пароль должен быть отклонён")
        assert client.connected is False
    finally:
        client.close()
        thread.join(2)
