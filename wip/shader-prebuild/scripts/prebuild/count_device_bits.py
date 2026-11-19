"""Counts graphics records of Lichii pipeline caches by their device bits (raw2 bit 12 =
provoking_vertex_last, and the raw1 dynamic-state flags KeyFitsDevice compares).

usage: python3.14 -I count_device_bits.py LICHII_PY_DIR cache.bin [cache.bin ...]
"""
import collections
import struct
import sys

sys.path.insert(0, sys.argv[1])
import lichii_cache as lc  # noqa: E402

for path in sys.argv[2:]:
    _, recs = lc.parse_cache(open(path, 'rb').read(), mesh_fields=True)
    g = [r for r in recs if not r.is_compute]
    pv = sum(1 for r in g if struct.unpack_from('<I', r.key, 52)[0] & 0x1000)
    pv_xfb = sum(1 for r in g if struct.unpack_from('<I', r.key, 52)[0] & 0x1000
                 and struct.unpack_from('<I', r.key, 48)[0] & 0x40)
    dyn = collections.Counter(hex(struct.unpack_from('<I', r.key, 48)[0] & 0x0010003F) for r in g)
    sc = collections.Counter(hex(struct.unpack_from('<I', r.key, 52)[0] & 0xFFFE7801) for r in g)
    print('%s: graphics %d, provoking_vertex_last %d (with xfb %d), raw1 dyn flags %s, raw2 scene flags %s'
          % (path.split('/')[-1], len(g), pv, pv_xfb, dict(dyn), dict(sc.most_common(6))))
