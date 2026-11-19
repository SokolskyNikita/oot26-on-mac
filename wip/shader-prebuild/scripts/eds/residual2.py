"""Splits the raw2 bits 12-14 effect (provoking vertex last, conservative raster, smooth lines)."""
import os
import struct, sys, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc, sms = ek.lc, ek.sms
keys, bits = [], collections.Counter()
for p in sys.argv[1:]:
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute or ek.is_mesh(r):
            continue
        st = sms.canonical(r.key[48:48 + lc.FPS_SIZE])
        k = r.key[:48] + ek.level_state(st, 3)
        keys.append(k)
        raw2 = struct.unpack_from('<I', k, 52)[0]
        bits[(raw2 >> 12) & 7] += 1
def zero(k, mask):
    b = bytearray(k); v = struct.unpack_from('<I', b, 52)[0] & ~mask
    struct.pack_into('<I', b, 52, v); return bytes(b)
out = {'records by bits12-14 value (1=provoking last, 2=conservative, 4=smooth lines)': dict(bits)}
for name, m in (('provoking_vertex_last', 1 << 12), ('conservative', 1 << 13), ('smooth_lines', 1 << 14)):
    out['L3 without ' + name] = len({zero(k, m) for k in keys})
# today's static keys too
print(json.dumps(out, indent=1))
