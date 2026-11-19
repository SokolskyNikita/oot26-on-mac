"""Non-empty entries of the UI manager's three arrays, with each object's vtable and any readable name."""
import re, sys; sys.path.insert(0, "."); import dbg; from dbg import call, kab
from pathlib import Path
dbg.MAIN = int(re.search(r"Module main loaded at (0x[0-9a-f]+)", (Path.home()/".local/share/lichii/log/eden_log.txt").read_text(errors="replace")).group(1), 16)
def q(a, n=1): return [int(x, 16) for x in call("read_memory", address=hex(a), size=8*n, **{"as": "u64"})["u64"]]
def cstr(a):
    try:
        b = bytes.fromhex(call("read_memory", address=hex(a), size=40)["hex"]).split(b"\0")[0]
        return b.decode() if len(b) > 2 and all(32 <= c < 127 for c in b) else None
    except Exception: return None
off = lambda v: f"main+{v - dbg.MAIN:#x}" if dbg.MAIN <= v < dbg.MAIN + 0x4ea0000 else hex(v)
ui = q(q(kab(0x84c9e098))[0])[0]
hdr = q(ui, 8)
for k, (cnt, arr) in enumerate([(hdr[1], hdr[2]), (hdr[3], hdr[4]), (hdr[5], hdr[6])]):
    ents = q(arr, min(cnt, 64)); live = [(i, e) for i, e in enumerate(ents) if e]
    print(f"list {k}: capacity {cnt}, {len(live)} set")
    for i, e in live[:20]:
        try:
            vt = q(e)[0]; words = q(e, 16)
            names = [f"+{j*8:#x}:{cstr(w)}" for j, w in enumerate(words) if w > 0x1000 and cstr(w)]
            print(f"  [{i}] {hex(e)} vt {off(vt)} {' '.join(names[:3])}")
        except Exception as ex: print(f"  [{i}] {hex(e)} ({ex})")
sm = q(kab(0x84eb7648))[0]; cur = q(sm + 0x1f0)[0]
print("scene mgr", hex(sm), "current scene", hex(cur), "vt", off(q(cur)[0]) if cur else "-")
