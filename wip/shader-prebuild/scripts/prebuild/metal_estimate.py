"""Estimated Metal cache use of a precompiled file (NX2PREP1), against the 1 GiB per-file cap.

Counts distinct Metal functions (vertex halves, fragment halves, compute records) with the
definitions of scripts/eds/eds_keys.metal_parts (static key, static rasterization), and
distinct shader programs per stage as the floor of distinct libraries. Bytes per entry are the
ranges in metal-shader-cache.md ("How many entries fit"): 19-25 KB a function, 35-45 KB a library.

usage: python3 -I metal_estimate.py FILE.nx2prep [FILE.nx2prep ...]
"""
import os
import collections
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eds'))
import eds_keys as ek  # noqa: E402
import state_model_static as sms  # noqa: E402  (eds_keys puts the builder's folder on the path)

GIB = 1 << 30
for path in sys.argv[1:]:
    with open(path, 'rb') as f:
        magic, version, n_envs, n_records, _ = struct.unpack('<8sIIII', f.read(24))
        assert magic == b'NX2PREP1'
        f.seek(24 + 16 * n_envs)
        vtx, frag, compute, programs = set(), set(), set(), collections.defaultdict(set)
        kinds = collections.Counter()
        for _ in range(n_records):
            kind, nids, _ = struct.unpack('<BBH', f.read(4))
            ids = struct.unpack('<%dI' % nids, f.read(4 * nids))
            if kind == 1:
                key = f.read(24)
                compute.add((key, ids))
                programs['compute'].add(key[:8])
                kinds['compute'] += 1
                continue
            key = f.read(1056)
            uh, state = key[:48], sms.canonical(key[48:48 + sms.STATE_LEN])
            v, fr, _ = ek.metal_parts(uh, state, dynamic_stride=False, static_raster=True)
            vtx.add(v)
            frag.add(fr)
            kinds['graphics'] += 1
            programs['pixel'].add(struct.unpack_from('<Q', uh, 40)[0])
            programs['vertex side'].add(uh[:40])
    functions = len(vtx) + len(frag) + len(compute)
    libraries = sum(len(s) for s in programs.values())
    print(path)
    print('  records %d (%s)' % (n_records, ', '.join('%s %d' % kv for kv in sorted(kinds.items()))))
    print('  distinct Metal functions %d: vertex halves %d, fragment halves %d, compute %d'
          % (functions, len(vtx), len(frag), len(compute)))
    print('  functions.data estimate %.2f-%.2f GiB (cap 1 GiB)' % (functions * 19e3 / GIB, functions * 25e3 / GIB))
    print('  distinct programs (library floor) %d: %s; libraries.data floor %.2f-%.2f GiB'
          % (libraries, ', '.join('%s %d' % (k, len(s)) for k, s in sorted(programs.items())),
             libraries * 35e3 / GIB, libraries * 45e3 / GIB))
