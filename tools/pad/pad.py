"""Drive the virtual controller (dsu_server.py must be running).

    python pad.py STEP [STEP ...]

Steps run in order:
  tap:a            press A for 0.12 s, then wait 0.12 s          tap:a:0.5 holds it 0.5 s
  chord:r+rdown    several inputs together for 0.3 s             chord:r+rdown:0.6
  hold:zl          press and keep           release:zl           let go           reset   everything off
  ls:0,1           left stick (x, y), each -1..1, y up; stays there until changed      rs:0,-1 right stick
  walk:0,1:2       left stick for 2 s, then back to centre
  wait:1.5         do nothing for 1.5 s

Buttons: a b x y l r zl zr plus minus up down left right l3 r3. In a chord, also lup ldown lleft lright
(left stick) and rup rdown rleft rright (right stick).
"""
import socket
import sys
import time

CONTROL = ("127.0.0.1", 26761)
STICK = {"lup": ("ls", 0, 1), "ldown": ("ls", 0, -1), "lleft": ("ls", -1, 0), "lright": ("ls", 1, 0),
         "rup": ("rs", 0, 1), "rdown": ("rs", 0, -1), "rleft": ("rs", -1, 0), "rright": ("rs", 1, 0)}
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1.0)


def send(text):
    sock.sendto(text.encode(), CONTROL)
    try:
        reply = sock.recvfrom(256)[0].decode()
    except socket.timeout:
        raise SystemExit("the virtual pad isn't running (start dsu_server.py)")
    if reply != "ok" and not text.startswith("state"):
        raise SystemExit(f"{text!r}: {reply}")
    return reply


def set_inputs(names, on):
    buttons = [n for n in names if n not in STICK]
    if buttons:
        send(("press " if on else "release ") + " ".join(buttons))
    for n in names:
        if n in STICK:
            stick, x, y = STICK[n]
            send(f"stick {stick} {x if on else 0} {y if on else 0}")


def run(step):
    kind, _, rest = step.partition(":")
    args = rest.split(":") if rest else []
    if kind == "tap":
        duration = float(args[1]) if len(args) > 1 else 0.12
        set_inputs([args[0]], True)
        time.sleep(duration)
        set_inputs([args[0]], False)
        time.sleep(0.12)
    elif kind == "chord":
        names = args[0].split("+")
        duration = float(args[1]) if len(args) > 1 else 0.3
        set_inputs(names[:1], True)        # the first input slightly ahead, as a hand would
        time.sleep(0.08)
        set_inputs(names[1:], True)
        time.sleep(duration)
        set_inputs(names, False)
        time.sleep(0.12)
    elif kind in ("hold", "release"):
        set_inputs(args[0].split("+"), kind == "hold")
    elif kind in ("ls", "rs"):
        x, y = args[0].split(",")
        send(f"stick {kind} {x} {y}")
    elif kind == "walk":
        x, y = args[0].split(",")
        send(f"stick ls {x} {y}")
        time.sleep(float(args[1]) if len(args) > 1 else 1.0)
        send("stick ls 0 0")
    elif kind == "wait":
        time.sleep(float(args[0]))
    elif kind == "reset":
        send("reset")
    elif kind == "state":
        print(send("state"))
    else:
        raise SystemExit(f"unknown step {step!r}\n{__doc__}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for s in sys.argv[1:]:
        run(s)
