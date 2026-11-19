#!/usr/bin/env python3
"""shotwatch.py OUT_DIR [--hz 10] [--min-white 0.5] [--min-vivid 0 (off)] [--ref-s 30] [--seconds N]
             [--min-frame 1500] [--on-bad]

Watches a running Lichii for a wrong picture. Asks the frame hook (../verify/hook.m, UDP 127.0.0.1:26799) for a
window capture --hz times a second, scores each one, and keeps only the captures whose scene has at least
--min-white percent clipped-white pixels or --min-vivid percent bright saturated pixels (persist.picture_metrics:
a clean Kokiri Forest scene scores 0.0 white, the canopy-shard picture of 2026-11-19 scored 2.6-2.8). Every capture
gets a line in OUT_DIR/shots.csv (wall time, presented frame, white %, vivid %, kept), so the timeline is there even
for the captures that were thrown away. One reference capture is kept every --ref-s seconds whatever it scores.
Captures before presented frame --min-frame are scored but never kept as bad (the boot logos are white).
With --on-bad, the first time ten captures in a row are bad in one boot it asks the debug server for a bug bundle
(capture_bundle) and a one-second GPU trace (trace_record), which land in that run's dumps folder.

It starts no emulator and takes no lock: run it beside a harness batch. While no Lichii answers it waits. A capture
runs inside Lichii, so frame times of a watched run are not clean measurements."""
import socket
import sys
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness"
sys.path.insert(0, str(HARNESS))
import persist  # noqa: E402
import dbg  # noqa: E402

PORT = 26799


def hook(cmd, timeout=2.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(cmd.encode(), ("127.0.0.1", PORT))
        return s.recvfrom(4096)[0].decode()
    except (socket.timeout, OSError):
        return ""
    finally:
        s.close()


def opt(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    hz, min_white, min_vivid = opt("--hz", 10.0), opt("--min-white", 0.5), opt("--min-vivid", 0.0)
    ref_s, seconds = opt("--ref-s", 30.0), opt("--seconds", 0.0)
    min_frame, on_bad = opt("--min-frame", 1500), "--on-bad" in sys.argv
    streak = 0; acted = -1
    tmp = out / "tmp.png"
    csv = open(out / "shots.csv", "a", buffering=1)
    if csv.tell() == 0:
        csv.write("wall_time,frame,white_pct,vivid_pct,capture_ms,kept\n")
    t_end = time.time() + seconds if seconds else None
    last_ref = 0.0; n = kept = 0; boot = 0; last_frame = -1
    while t_end is None or time.time() < t_end:
        t0 = time.time()
        r = hook(f"shot {tmp}")
        ms = (time.time() - t0) * 1e3
        if not r.startswith("ok"):
            time.sleep(1.0)
            continue
        frame = int(r.split()[1])
        if frame < last_frame:
            boot += 1                                     # the frame count started again: another Lichii
        last_frame = frame
        try:
            m = persist.picture_metrics(tmp)
        except Exception as e:                            # a half-written or odd capture: skip it
            csv.write(f"{t0:.3f},{frame},,,{ms:.0f},error {type(e).__name__}\n"); continue
        bad = frame >= min_frame and (m["clipped_pct"] >= min_white or (min_vivid > 0 and m["vivid_pct"] >= min_vivid))
        streak = streak + 1 if bad else 0
        if on_bad and streak >= 10 and acted != boot:
            acted = boot
            for method, params in (("capture_bundle", {"description": "shotwatch: bad picture", "size_limit_mib": 60}),
                                   ("trace_record", {"presents": 60})):
                try:
                    res = dbg.call(method, timeout=300, **params)
                    print(f"{time.strftime('%H:%M:%S')} boot {boot} frame {frame}: {method} -> {str(res)[:300]}", flush=True)
                except Exception as e:
                    print(f"{time.strftime('%H:%M:%S')} boot {boot} frame {frame}: {method} failed: {e}", flush=True)
        ref = t0 - last_ref >= ref_s
        keep = ""
        if bad or ref:
            name = f"{'bad' if bad else 'ref'}-b{boot}-f{frame:06d}.png"
            tmp.rename(out / name); keep = name; kept += bad
            if ref:
                last_ref = t0
        csv.write(f"{t0:.3f},{frame},{m['clipped_pct']},{m['vivid_pct']},{ms:.0f},{keep}\n")
        n += 1
        if n % 100 == 0:
            print(f"{time.strftime('%H:%M:%S')} {n} captures, {kept} kept as bad, last frame {frame}, "
                  f"white {m['clipped_pct']} vivid {m['vivid_pct']}, capture {ms:.0f} ms", flush=True)
        time.sleep(max(0.0, 1.0 / hz - (time.time() - t0)))
    print(f"done: {n} captures, {kept} kept as bad")


if __name__ == "__main__":
    main()
