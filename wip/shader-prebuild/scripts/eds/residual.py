"""Which key fields keep EDS3 keys apart beyond what Metal compiles (diagnostic for eds_keys.py)."""
import os
import struct, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek
lc, sms = ek.lc, ek.sms
FIELDS = {
    'app_stage (raw2 17-19)': (4, 0x7 << 17),
    'provoking/conservative/smooth (raw2 12-14)': (4, 0x7 << 12),
    'depth enable+format (raw2 5-10)': (4, 0x3F << 5),
    'logic_op+enable, stipple (ds raw1 6-12)': (72, 0x7F << 6),
    'alpha_test_ref': (24, 0xFFFFFFFF),
    'point_size': (28, 0xFFFFFFFF),
}
keys = []
for p in sys.argv[1:]:
    _, recs = lc.parse_cache(open(p, 'rb').read())
    for r in recs:
        if r.is_compute or ek.is_mesh(r):
            continue
        st = sms.canonical(r.key[48:48 + lc.FPS_SIZE])
        keys.append(r.key[:48] + ek.level_state(st, 3))
def zero(k, off, mask):
    b = bytearray(k); v = struct.unpack_from('<I', b, 48 + off)[0] & ~mask
    struct.pack_into('<I', b, 48 + off, v); return bytes(b)
out = {'L3': len(set(keys))}
allz = keys
for name, (off, mask) in FIELDS.items():
    out['without ' + name] = len({zero(k, off, mask) for k in keys})
    allz = [zero(k, off, mask) for k in allz]
out['without all of these'] = len(set(allz))
out['without all + swizzles'] = len({k[:48+32] + bytes(32) + k[48+64:] for k in allz})
print(json.dumps(out, indent=1))
