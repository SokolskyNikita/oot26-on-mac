# Pull every zstd-compressed SPIR-V module out of Lichii's kept store (read-only), dedupe, write by stage.
# Usage: python3 -I extract_spv.py OUTDIR KEPT_STORE
import sys, mmap, struct, hashlib, os
from compression import zstd
from collections import Counter
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
f = open(sys.argv[2], 'rb'); m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
MODEL = {0: 'vertex', 1: 'tesc', 2: 'tese', 3: 'geom', 4: 'fragment', 5: 'kernel', 5364: 'object', 5365: 'mesh'}
pos = 0; frames = 0; errs = 0; seen = set(); c = Counter()
while True:
    i = m.find(b'\x28\xb5\x2f\xfd', pos)
    if i < 0: break
    pos = i + 4
    try:
        d = zstd.ZstdDecompressor(); spv = d.decompress(m[i:i + 8_000_000])
    except Exception:
        errs += 1; continue
    frames += 1
    if spv[:4] != b'\x03\x02\x23\x07': c['notspv'] += 1; continue
    w = struct.unpack(f'<{len(spv)//4}I', spv[:len(spv)//4*4]); j = 5; model = None
    while j < len(w):
        op = w[j] & 0xffff; n = w[j] >> 16
        if n == 0: break
        if op == 15: model = MODEL.get(w[j+1], str(w[j+1])); break
        j += n
    h = hashlib.sha1(spv).hexdigest()[:16]
    if h in seen: c['dup'] += 1; continue
    seen.add(h); c[model] += 1
    open(f'{out}/{h}.{model}.spv', 'wb').write(spv)
    pos = i + max(4, len(d.unused_data) and 4)
print('frames', frames, 'errs', errs, dict(c))
