#!/bin/bash
set -eu

cat >/usr/local/bin/mdt_dns4.py <<'PY'
#!/usr/bin/env python3
import socket
import struct

TARGET = b"c9800-mdt-grpc-demo-xv5kzbkaga-uc.a.run.app"
ADDRESSES = [
    "34.143.75.2",
    "34.143.77.2",
    "34.143.72.2",
    "34.143.76.2",
    "34.143.73.2",
    "34.143.74.2",
    "34.143.78.2",
    "34.143.79.2",
]


def decode_name(packet, offset):
    labels = []
    while True:
        length = packet[offset]
        offset += 1
        if length == 0:
            return b".".join(labels), offset
        if length & 0xC0:
            raise ValueError("compressed query name is not supported")
        labels.append(packet[offset : offset + length].lower())
        offset += length


def response(packet):
    if len(packet) < 12:
        return b""
    query_id = packet[:2]
    flags = struct.unpack("!H", packet[2:4])[0]
    questions = struct.unpack("!H", packet[4:6])[0]
    if questions != 1:
        return b""

    name, offset = decode_name(packet, 12)
    if offset + 4 > len(packet):
        return b""
    query_type, query_class = struct.unpack("!HH", packet[offset : offset + 4])
    question_end = offset + 4
    question = packet[12:question_end]
    is_target = name == TARGET.lower() and query_class == 1 and query_type == 1
    answers = []
    if is_target:
        for address in ADDRESSES:
            answers.append(
                b"\xc0\x0c"
                + struct.pack("!HHIH", 1, 1, 30, 4)
                + socket.inet_aton(address)
            )

    header = query_id + struct.pack("!HHHHH", (flags & 0x0100) | 0x8000, 1, len(answers), 0, 0)
    return header + question + b"".join(answers)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 53))
while True:
    packet, address = sock.recvfrom(4096)
    try:
        reply = response(packet)
        if reply:
            sock.sendto(reply, address)
    except Exception:
        pass
PY

chmod 0755 /usr/local/bin/mdt_dns4.py
nohup /usr/bin/python3 /usr/local/bin/mdt_dns4.py >/var/log/mdt_dns4.log 2>&1 &
