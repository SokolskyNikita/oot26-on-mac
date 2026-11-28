"""extract_msl.py CACHE OUTDIR: write every unique Metal source held in MoltenVK's pipeline cache
(~/.cache/lichii/shader/<title>/vulkan_pipelines.fork-v54.bin) as OUTDIR/<stage>-<hash>.metal.
Copy the cache first: Lichii rewrites it while it runs. The output is game code; keep it in ../local/."""
import re, struct, hashlib, sys, os, collections
d = open(sys.argv[1], "rb").read(); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
seen = set(); kinds = collections.Counter()
for m in re.finditer(rb"#include <metal_stdlib>", d):
    s = m.start()
    while d[s - 1] in (10, 9) or 32 <= d[s - 1] < 127: s -= 1
    for k in range(9):  # the source is preceded by its length as a 64-bit integer
        st = s + k; n = struct.unpack_from("<Q", d, st - 8)[0]
        if 100 < n < 5_000_000 and st + n <= len(d) and d[st + n - 1:st + n] in (b"\n", b"}"): break
    else: continue
    src = d[st:st + n]; h = hashlib.sha1(src).hexdigest()[:12]
    if h in seen: continue
    seen.add(h); t = src.decode()
    kind = ("fs" if re.search(r"^fragment ", t, re.M) else "vs" if re.search(r"^vertex ", t, re.M)
            else "cs" if re.search(r"^kernel ", t, re.M) else "ms" if "[[mesh" in t else "ot")
    kinds[kind] += 1
    open(f"{out}/{kind}-{h}.metal", "w").write(t)
print(dict(kinds))
