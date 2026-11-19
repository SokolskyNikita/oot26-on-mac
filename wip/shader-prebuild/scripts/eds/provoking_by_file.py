"""Provoking-vertex-last bit (raw2 bit 12) of graphics records, per cache file."""
import os
import struct, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc = ek.lc
for p in sys.argv[1:]:
    c = collections.Counter()
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute:
            continue
        raw2 = struct.unpack_from('<I', r.key, 52)[0]
        c[('mesh' if ek.is_mesh(r) else 'vp', (raw2 >> 12) & 1)] += 1
    print(p.rsplit('/', 1)[1], dict(sorted(c.items())))
