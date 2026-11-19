"""Held-out overlap: of the last cache's graphics keys, how many the other caches already hold, per level.
A proxy for how often a state must be guessed rather than replayed (not the state model itself)."""
import os
import struct, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc, sms = ek.lc, ek.sms
PROV = 1 << 12
def variants(st):
    out = {}
    for lvl in (0, 1, 2, 3):
        out[f'L{lvl}'] = ek.level_state(st, lvl)
    for name, lvl in (('L0_no_provoking', 0), ('L3_no_provoking', 3)):
        b = bytearray(ek.level_state(st, lvl))
        struct.pack_into('<I', b, 4, struct.unpack_from('<I', b, 4)[0] & ~PROV)
        out[name] = bytes(b)
    return out
def load(paths):
    keys, combos = {}, set()
    for p in paths:
        _, recs = lc.parse_cache(open(p, 'rb').read())
        for r in recs:
            if r.is_compute or ek.is_mesh(r):
                continue
            st = sms.canonical(r.key[48:48 + lc.FPS_SIZE])
            combos.add(r.key[:48])
            for name, s in variants(st).items():
                keys.setdefault(name, set()).add(r.key[:48] + s)
    return keys, combos
train, train_combos = load(sys.argv[1:-1])
test, _ = load(sys.argv[-1:])
out = {}
for name in test:
    t = test[name]
    known_combo = {k for k in t if k[:48] in train_combos}
    out[name] = {'test_keys': len(t), 'already_recorded': len(t & train[name]),
                 'known_shaders_new_state': len(known_combo - train[name]),
                 'new_shaders': len(t) - len(known_combo)}
print(json.dumps(out, indent=1))
