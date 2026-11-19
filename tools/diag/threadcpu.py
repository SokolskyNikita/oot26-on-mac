#!/usr/bin/env python3
"""threadcpu.py PID SECONDS [--wait-s N]: CPU time of every thread of a process over a window, by thread name.

Reads each thread's user and system time twice through libproc (proc_pidinfo), SECONDS apart, without stopping the
process (unlike `sample`) and without sudo for a process of the same user. Prints threads by CPU used in the window,
in ms per second of wall time, grouped by name with trailing numbers folded together."""
import ctypes
import re
import sys
import time
from collections import defaultdict

libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
PROC_PIDLISTTHREADS, PROC_PIDTHREADINFO = 6, 5


class ThreadInfo(ctypes.Structure):
    _fields_ = [("user", ctypes.c_uint64), ("system", ctypes.c_uint64), ("cpu_usage", ctypes.c_int32),
                ("policy", ctypes.c_int32), ("run_state", ctypes.c_int32), ("flags", ctypes.c_int32),
                ("sleep_time", ctypes.c_int32), ("curpri", ctypes.c_int32), ("priority", ctypes.c_int32),
                ("maxpriority", ctypes.c_int32), ("name", ctypes.c_char * 64)]


class Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def snapshot(pid):
    buf = (ctypes.c_uint64 * 4096)()
    n = libproc.proc_pidinfo(pid, PROC_PIDLISTTHREADS, ctypes.c_uint64(0), buf, ctypes.sizeof(buf))
    out = {}
    for h in buf[: max(n, 0) // 8]:
        ti = ThreadInfo()
        if libproc.proc_pidinfo(pid, PROC_PIDTHREADINFO, ctypes.c_uint64(h), ctypes.byref(ti),
                                ctypes.sizeof(ti)) == ctypes.sizeof(ti):
            out[h] = (ti.user, ti.system, ti.name.decode(errors="replace"), ti.priority)
    return out


def main():
    pid, seconds = int(sys.argv[1]), float(sys.argv[2])
    if "--wait-s" in sys.argv:
        time.sleep(float(sys.argv[sys.argv.index("--wait-s") + 1]))
    tb = Timebase(); libc.mach_timebase_info(ctypes.byref(tb))
    a = snapshot(pid); t0 = time.time()
    time.sleep(seconds)
    b = snapshot(pid); wall = time.time() - t0
    if not a or not b:
        print("no threads read (is the pid right, and the process yours?)"); return
    groups = defaultdict(lambda: [0.0, 0.0, 0])
    total = 0.0
    for h, (u1, s1, name, pri) in b.items():
        u0, s0 = a.get(h, (0, 0, "", 0))[:2]
        # the times are nanoseconds on this macOS; if not, the timebase converts mach units
        du, ds = (u1 - u0) / 1e6, (s1 - s0) / 1e6
        key = re.sub(r"[\s:#_-]*\d+$", "", name) or "(unnamed)"
        g = groups[key]; g[0] += du; g[1] += ds; g[2] += 1
        total += du + ds
    print(f"pid {pid}: {len(b)} threads, window {wall:.1f} s, timebase {tb.numer}/{tb.denom}; "
          f"all threads {total / wall:.0f} ms of CPU per second ({total / wall / 1000:.2f} cores)")
    print(f"{'thread name':40s} {'threads':>7s} {'ms/s':>8s} {'user':>7s} {'system':>7s}")
    for key, (u, s, n) in sorted(groups.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
        if (u + s) / wall < 5:
            continue
        print(f"{key[:40]:40s} {n:7d} {(u + s) / wall:8.0f} {u / wall:7.0f} {s / wall:7.0f}")


if __name__ == "__main__":
    main()
