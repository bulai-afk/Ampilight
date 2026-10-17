import socket
import threading

from app.discover import addresses_in_mdns, has_lan_address, hosts_in_subnet, looks_like_hyperion, probe


def test_subnet_skips_self_and_stays_small():
    ip = socket.inet_aton("192.168.100.7")
    ip_i = int.from_bytes(ip, "big")
    hosts = hosts_in_subnet(ip_i, 0xFFFFFF00)
    assert "192.168.100.7" not in hosts
    assert "192.168.100.1" in hosts
    assert "192.168.100.254" in hosts
    assert "192.168.100.255" not in hosts
    assert len(hosts) == 253


def test_wifi_address_counts_as_online():
    def ip(text: str) -> int:
        return int.from_bytes(socket.inet_aton(text), "big")

    assert has_lan_address(ip("192.168.100.7"))
    assert not has_lan_address(ip("127.0.0.1"))
    assert not has_lan_address(ip("169.254.1.1"))


def test_hyperion_reply_is_recognized():
    assert looks_like_hyperion(b'{"success":true,"info":{"hyperion":[]}}\n')
    assert looks_like_hyperion(b'{"command":"serverinfo","info":{"hostname":"desk"}}\n')
    assert not looks_like_hyperion(b"")
    assert not looks_like_hyperion(b"HTTP/1.1 200 OK")


def test_mdns_query_asks_for_direct_reply():
    from app.discover import _query

    assert b"\x00\x0c\x80\x01" in _query("_hyperiond-json._tcp.local")


def test_mdns_packet_yields_hyperion_address():
    packet = b"hyperiond" + b"\x00\x01\x00\x01" + b"\x00\x00\x00\x10" + b"\x00\x04" + bytes([192, 168, 100, 7])
    assert addresses_in_mdns(packet) == ["192.168.100.7"]
    assert addresses_in_mdns(b"\x00\x01\x00\x01" + b"\x00\x00\x00\x10" + b"\x00\x04" + bytes([1, 2, 3, 4])) == []


def test_probe_talks_to_a_local_hyperion():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve() -> None:
        conn, _addr = server.accept()
        conn.recv(1024)
        conn.sendall(
            b'{"success":true,"info":{"hostname":"\xd1\x81\xd1\x82\xd0\xbe\xd0\xbb",'
            b'"leds":[{},{},{}],"instance":[{},{}]}}\n'
        )
        conn.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert probe("127.0.0.1", port, 1.0) == ("стол", 2)
    thread.join(1)
