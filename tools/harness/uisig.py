"""One-line UI state: the set slots of the UI manager's screen list (slot:vtable as main offset) and the scene's vtable."""
import re, sys; sys.path.insert(0, "."); import dbg; from dbg import call, kab
from pathlib import Path
def setup():
    dbg.MAIN = int(re.search(r"Module main loaded at (0x[0-9a-f]+)", (Path.home()/".local/share/lichii/log/eden_log.txt").read_text(errors="replace")).group(1), 16)
def q(a, n=1): return [int(x, 16) for x in call("read_memory", address=hex(a), size=8*n, **{"as": "u64"})["u64"]]
def sig():
    ui = q(q(kab(0x84c9e098))[0])[0]; cnt, arr = q(ui + 8, 2)
    ents = q(arr, cnt)
    scr = {i: q(e)[0] - dbg.MAIN for i, e in enumerate(ents) if e}
    sm = q(kab(0x84eb7648))[0]; cur = q(sm + 0x1f0)[0]
    return {"screens": {i: hex(v) for i, v in sorted(scr.items())}, "scene": hex(q(cur)[0] - dbg.MAIN) if cur else None}
if __name__ == "__main__":
    setup(); print(sig())
