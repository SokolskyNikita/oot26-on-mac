"""Distinct keys per level with the provoking-vertex bit cleared (it differs between the builds that
recorded the caches, not between draws: cache3 never sets it), for vertex/pixel and mesh records,
plus states per shader combination. Writes final_counts.json."""
import os
import struct, sys, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc, sms = ek.lc, ek.sms
PROV = 1 << 12
per = {g: {l: collections.defaultdict(set) for l in range(4)} for g in ('vp', 'mesh')}
for p in sys.argv[1:]:
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute:
            continue
        g = 'mesh' if ek.is_mesh(r) else 'vp'
        b = bytearray(sms.canonical(r.key[48:48 + lc.FPS_SIZE]))
        struct.pack_into('<I', b, 4, struct.unpack_from('<I', b, 4)[0] & ~PROV)
        for l in range(4):
            per[g][l][r.key[:48]].add(ek.level_state(bytes(b), l))
out = {}
for g, levels in per.items():
    for l, d in levels.items():
        sizes = [len(v) for v in d.values()]
        out[f'{g} L{l}'] = {'combinations': len(sizes), 'keys': sum(sizes),
                            'one_state': sum(s == 1 for s in sizes),
                            'extra_states': sum(sizes) - len(sizes), 'max': max(sizes)}
json.dump(out, open('final_counts.json', 'w'), indent=1)
print(json.dumps(out, indent=1))
