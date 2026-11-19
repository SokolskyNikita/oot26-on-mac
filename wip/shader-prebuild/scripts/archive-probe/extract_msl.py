# Extract MSL sources (length-prefixed u64 strings) from Lichii/MoltenVK pipeline cache blobs. Read-only on inputs.
# Usage: python3 -I extract_msl.py OUTDIR BLOB...
import sys, mmap, struct, hashlib, os, re
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
seen = {}; stats = {}
for path in sys.argv[2:]:
    f = open(path, 'rb'); m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    pos = 0; n = 0; bad = 0
    while True:
        i = m.find(b'#include <metal_stdlib>', pos)
        if i < 0: break
        k = i
        while k > 0 and (32 <= m[k-1] < 127 or m[k-1] in (9, 10, 13)): k -= 1
        ln = struct.unpack('<Q', m[k-8:k])[0]
        pos = i + 1
        if not (100 < ln < 50_000_000) or k + ln > len(m): bad += 1; continue
        src = bytes(m[k:k+ln])
        if b'\x00' in src: bad += 1; continue
        n += 1
        h = hashlib.sha1(src).hexdigest()[:16]
        if h in seen: continue
        s = src.decode('utf-8', 'replace')
        kind = 'vertex' if re.search(r'^vertex ', s, re.M) else 'fragment' if re.search(r'^fragment ', s, re.M) else \
               'kernel' if re.search(r'^kernel ', s, re.M) else 'mesh' if '[[mesh]]' in s else 'object' if '[[object]]' in s else 'other'
        seen[h] = kind
        open(f'{out}/{h}.{kind}.metal', 'wb').write(src)
        pos = k + ln
    stats[path] = (n, bad)
from collections import Counter
print(stats); print(len(seen), Counter(seen.values()))
