"""Distinct states per shader combination (unique_hashes) at each level: how predictable a key is."""
import os
import struct, sys, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc, sms = ek.lc, ek.sms
PROV = 1 << 12
per = {name: collections.defaultdict(set) for name in ('L0', 'L1', 'L2', 'L3', 'L3_no_provoking', 'L0_no_provoking')}
for p in sys.argv[1:]:
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute or ek.is_mesh(r):
            continue
        st = sms.canonical(r.key[48:48 + lc.FPS_SIZE])
        uh = r.key[:48]
        for lvl in range(4):
            per[f'L{lvl}'][uh].add(ek.level_state(st, lvl))
        for name, lvl in (('L3_no_provoking', 3), ('L0_no_provoking', 0)):
            b = bytearray(ek.level_state(st, lvl))
            struct.pack_into('<I', b, 4, struct.unpack_from('<I', b, 4)[0] & ~PROV)
            per[name][uh].add(bytes(b))
out = {}
for name, d in per.items():
    sizes = [len(v) for v in d.values()]
    out[name] = {'shader_combinations': len(sizes), 'keys': sum(sizes),
                 'combinations_with_one_state': sum(1 for s in sizes if s == 1),
                 'keys_beyond_first_per_combination': sum(sizes) - len(sizes),
                 'max_states': max(sizes)}
print(json.dumps(out, indent=1))
