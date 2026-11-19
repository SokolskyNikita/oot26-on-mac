"""A virtual controller for the emulator, with no window focus needed.

The emulator (Lichii, like the yuzu family) polls a "cemuhook" / DSU controller server on 127.0.0.1:26760. This
is such a server: it reports one pad whose buttons and sticks are whatever was last set through its control
socket (UDP 127.0.0.1:26761, one text command per datagram; see pad.py for the client and the commands).

    python dsu_server.py            # runs until killed

Protocol (little endian), from the emulator's own src/input_common/helpers/udp_protocol.h:
  header: "DSUC"/"DSUS", u16 version 1001, u16 payload length (everything after the header), u32 crc32 of the
          packet with this field zero, u32 sender id; then u32 message type and its body
  0x100000 version, 0x100001 port info (12 bytes: id, state, model, connection, mac[6], battery, active),
  0x100002 pad data (80 bytes: the 11 info bytes, u8 connected, u32 packet counter, u16 buttons, home, touch
          button, left x, left y, right x, right y, 12 analog buttons, 2 touch points, u64 time, accel, gyro)
Button bits, low to high: share(minus) L3 R3 options(plus) up right down left L2(ZL) R2(ZR) L1(L) R1(R)
triangle(X) circle(A) cross(B) square(Y). Sticks are 0..255, 128 centre; y grows upward.
"""
import select
import socket
import struct
import time
import zlib

DSU_PORT, CONTROL_PORT = 26760, 26761
SERVER_ID = 0x0C0FFEE0
RATE_HZ = 250
BITS = {"minus": 0, "l3": 1, "r3": 2, "plus": 3, "up": 4, "right": 5, "down": 6, "left": 7,
        "zl": 8, "zr": 9, "l": 10, "r": 11, "x": 12, "a": 13, "b": 14, "y": 15}
MAC = bytes([0x0C, 0x0F, 0xFE, 0xE0, 0x00, 0x01])


class Pad:
    def __init__(self):
        self.buttons = 0
        self.sticks = {"ls": (0.0, 0.0), "rs": (0.0, 0.0)}
        self.counter = 0

    def command(self, text):
        """press NAME... | release NAME... | stick ls|rs X Y (each -1..1, y up) | reset -> reply text"""
        parts = text.strip().lower().split()
        if not parts:
            return "empty"
        verb, args = parts[0], parts[1:]
        if verb in ("press", "release"):
            for name in args:
                if name not in BITS:
                    return f"unknown button {name}"
                if verb == "press":
                    self.buttons |= 1 << BITS[name]
                else:
                    self.buttons &= ~(1 << BITS[name])
            return "ok"
        if verb == "stick" and len(args) == 3 and args[0] in self.sticks:
            self.sticks[args[0]] = (max(-1.0, min(1.0, float(args[1]))), max(-1.0, min(1.0, float(args[2]))))
            return "ok"
        if verb == "reset":
            self.buttons = 0
            self.sticks = {"ls": (0.0, 0.0), "rs": (0.0, 0.0)}
            return "ok"
        if verb == "state":
            return f"buttons {self.buttons:#06x} sticks {self.sticks} packets {self.counter}"
        return f"unknown command {verb}"

    def info(self):
        # id 0, connected, full-gyro model, USB, mac, battery full
        return struct.pack("<BBBB6sB", 0, 2, 2, 1, MAC, 5)

    def data(self):
        self.counter += 1
        axis = lambda v: max(0, min(255, int(round(128 + v * 127))))   # noqa: E731
        ls, rs = self.sticks["ls"], self.sticks["rs"]
        b = self.buttons
        analog = bytes(255 if b >> BITS[n] & 1 else 0 for n in
                       ("left", "down", "right", "up", "y", "b", "a", "x", "r", "l", "zr", "zl"))
        return (self.info() + struct.pack("<BIHBB4B", 1, self.counter, b, 0, 0, axis(ls[0]), axis(ls[1]), axis(rs[0]),
                                          axis(rs[1])) + analog + bytes(12) +
                struct.pack("<Q6f", int(time.time() * 1e6), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


def packet(kind, body):
    payload = struct.pack("<I", kind) + body
    head = struct.pack("<4sHHII", b"DSUS", 1001, len(payload), 0, SERVER_ID)
    crc = zlib.crc32(head + payload) & 0xFFFFFFFF
    return struct.pack("<4sHHII", b"DSUS", 1001, len(payload), crc, SERVER_ID) + payload


def main():
    dsu = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dsu.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dsu.bind(("127.0.0.1", DSU_PORT))
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    control.bind(("127.0.0.1", CONTROL_PORT))
    pad = Pad()
    clients = {}   # address -> time of its last pad-data request
    next_send = time.monotonic()
    print(f"virtual pad: DSU on 127.0.0.1:{DSU_PORT}, control on 127.0.0.1:{CONTROL_PORT}", flush=True)
    while True:
        timeout = max(0.0, next_send - time.monotonic())
        ready, _, _ = select.select([dsu, control], [], [], timeout)
        for sock in ready:
            msg, addr = sock.recvfrom(2048)
            if sock is control:
                control.sendto(pad.command(msg.decode("utf-8", "replace")).encode(), addr)
                continue
            if len(msg) < 20 or msg[:4] != b"DSUC":
                continue
            kind = struct.unpack_from("<I", msg, 16)[0]
            if kind == 0x100000:
                dsu.sendto(packet(kind, struct.pack("<H", 1001)), addr)
            elif kind == 0x100001:
                count = struct.unpack_from("<I", msg, 20)[0]
                for port in msg[24:24 + min(count, 4)]:
                    if port == 0:
                        dsu.sendto(packet(kind, pad.info() + b"\0"), addr)
                    else:   # an empty slot
                        dsu.sendto(packet(kind, struct.pack("<BBBB6sBB", port, 0, 0, 0, bytes(6), 0, 0)), addr)
            elif kind == 0x100002:
                if addr not in clients:
                    print("emulator connected from", addr, flush=True)
                clients[addr] = time.monotonic()
        now = time.monotonic()
        if now >= next_send:
            next_send = now + 1.0 / RATE_HZ
            for addr, seen in list(clients.items()):
                if now - seen > 10:
                    del clients[addr]
                    print("emulator went quiet:", addr, flush=True)
                else:
                    dsu.sendto(packet(0x100002, pad.data()), addr)


if __name__ == "__main__":
    main()
