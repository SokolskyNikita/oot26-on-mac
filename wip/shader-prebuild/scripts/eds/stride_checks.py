"""Records with a vertex attribute read from a binding of stride 0, and tessellation records:
both meet MoltenVK's dynamic-stride paths (MoltenVK issues #2041, #2428)."""
import os
import struct, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc = ek.lc
c = collections.Counter(); strides = collections.Counter()
for p in sys.argv[1:]:
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute or ek.is_mesh(r):
            continue
        st = r.key[48:]
        c['vp records'] += 1
        zero = False
        for i in range(32):
            a = struct.unpack_from('<I', st, 112 + 4 * i)[0]
            if a & 1:
                buf = (a >> 1) & 31
                s = struct.unpack_from('<H', st, 368 + 2 * buf)[0]
                strides[s] += 1
                zero |= s == 0
        c['with an attribute on a stride-0 binding'] += zero
        topo = (struct.unpack_from('<I', st, 0)[0] >> 24) & 0xF
        c['patches (tessellation)'] += topo == 14
        c[f'topology {topo}'] += 1
print(dict(c)); print('attribute strides', dict(strides.most_common(12)))
