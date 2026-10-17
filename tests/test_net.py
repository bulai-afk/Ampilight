import socket
import struct

from app.sender import subnet_broadcast


def _ip(text: str) -> int:
    return struct.unpack("!I", socket.inet_aton(text))[0]


def test_broadcast_matches_the_board_subnet():
    subnets = [(_ip("192.168.100.3"), _ip("255.255.255.0"), "192.168.100.255")]
    assert subnet_broadcast("192.168.100.7", subnets) == "192.168.100.255"
    assert subnet_broadcast("10.0.0.4", subnets) is None
