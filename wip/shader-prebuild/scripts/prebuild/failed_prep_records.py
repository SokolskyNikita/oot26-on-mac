"""Lists the records a preparation marked failed (or left out as interrupted twice) in a
precompiled store, with each one's record in the precompiled file.

usage: python3.14 -I failed_prep_records.py LICHII_PY_DIR precompiled.nx2prep precompiled_kept_index.bin
       [--recorded-graphics N --predicted-graphics P --oracle-compute M]   (the builder's report: records written in order
       recorded graphics, predicted graphics, predicted mesh, compute; the first
       (compute records - oracle compute) compute records are recorded ones)
Also prints how many graphics records carry provoking_vertex_last (raw2 bit 12) and how many of
those have a twin with the bit clear in the file.
"""
import argparse
import collections
import struct
import sys

ap = argparse.ArgumentParser()
ap.add_argument('py')
ap.add_argument('prep')
ap.add_argument('index')
ap.add_argument('--recorded-graphics', type=int)
ap.add_argument('--oracle-compute', type=int)
ap.add_argument('--predicted-graphics', type=int)
args = ap.parse_args()
sys.path.insert(0, args.py)
import lichii_cache as lc  # noqa: E402

# The precompiled file's records (the environments are not read).
with open(args.prep, 'rb') as f:
    magic, version, nenv, nrec, _ = struct.unpack('<8sIIII', f.read(24))
    assert magic == b'NX2PREP1'
    index = f.read(16 * nenv)
    env_offsets = [struct.unpack_from('<QQ', index, 16 * i) for i in range(nenv)]
    body = f.read(env_offsets[0][0] - 24 - 16 * nenv) if nenv else b''
records = []
o = 0
for _ in range(nrec):
    kind, count, _ = struct.unpack_from('<BBH', body, o)
    o += 4
    ids = struct.unpack_from('<%dI' % count, body, o)
    o += 4 * count
    size = 1056 if kind == 0 else 24
    records.append((kind, ids, body[o:o + size]))
    o += size
assert o == len(body), (o, len(body))
n_graphics = sum(1 for r in records if r[0] == 0)
first_compute = next(i for i, r in enumerate(records) if r[0] == 1)
n_compute = nrec - first_compute
print('file: version %d, environments %d, records %d (graphics %d, compute %d from index %d)'
      % (version, nenv, nrec, n_graphics, n_compute, first_compute))


def origin(i):
    kind = records[i][0]
    if kind == 1:
        if args.oracle_compute is None:
            return 'compute'
        return 'compute, ' + ('recorded' if i - first_compute < n_compute - args.oracle_compute else 'oracle')
    if args.recorded_graphics is not None and i < args.recorded_graphics:
        return 'graphics, recorded'
    if args.predicted_graphics is not None and i >= args.recorded_graphics + args.predicted_graphics:
        return 'mesh, predicted'
    return 'graphics, predicted'


def describe(i):
    kind, ids, key = records[i]
    if kind == 1:
        h, shared, *wg = struct.unpack_from('<QI3I', key, 0)
        return 'compute %016x shared %d workgroup %s' % (h, shared, wg)
    hs = struct.unpack_from('<6Q', key, 0)
    raw1, raw2 = struct.unpack_from('<II', key, 48)
    return 'graphics hashes %s envs %d raw1 %#x raw2 %#x' % (
        ' '.join('%016x' % h for h in hs if h), len(ids), raw1, raw2)


# The store index.
data = open(args.index, 'rb').read()
magic, ver, rec_count, stamp_size = struct.unpack_from('<8sIII', data, 0)
assert magic == b'NX2PIDX1', magic
o = 20 + stamp_size
print('index: version %d, record count %d (file %d), stamp %d bytes' % (ver, rec_count, nrec, stamp_size))
state = {}
starts = collections.Counter()
ends = collections.Counter()
entries = collections.Counter()
while o < len(data):
    t = data[o]
    if t == 1:
        o += 24
    elif t == 2:
        if o + 76 > len(data):
            break
        _, n, flags, _, rec, key_hash = struct.unpack_from('<BBBBIQ', data, o)
        state[rec] = flags
        ends[rec] += 1
        o += 76
    elif t in (3, 4):
        rec = struct.unpack_from('<I', data, o + 4)[0]
        (starts if t == 3 else ends)[rec] += 1
        o += 8
    else:
        print('unknown entry %d at %d; stopping' % (t, o))
        break
    entries[t] += 1
print('entries', dict(entries), 'records prepared', len(state))
failed = sorted(r for r, fl in state.items() if fl & 2)
poisoned = sorted(r for r, n in starts.items() if n >= 2 and ends[r] == 0)
print('failed', len(failed), 'started twice, never finished', len(poisoned))
groups = collections.Counter()
for r in failed:
    print('  failed   %7d  %-20s %s' % (r, origin(r), describe(r)))
    groups[origin(r)] += 1
for r in poisoned:
    print('  poisoned %7d  %-20s %s' % (r, origin(r), describe(r)))
print('failed by origin', dict(groups))

# Records never prepared, and provoking_vertex_last.
pv = [i for i, r in enumerate(records) if r[0] == 0 and struct.unpack_from('<I', r[2], 52)[0] & 0x1000]
keys = {r[2] for r in records if r[0] == 0}
twins = sum(1 for i in pv if records[i][2][:52] + struct.pack('<I', struct.unpack_from('<I', records[i][2], 52)[0] & ~0x1000) + records[i][2][56:] in keys)
print('graphics records with provoking_vertex_last: %d (with a twin whose bit is clear: %d); prepared: %d'
      % (len(pv), twins, sum(1 for i in pv if i in state)))
never = [i for i in range(nrec) if i not in state]
print('records with no prepared entry: %d (of them provoking_vertex_last: %d)'
      % (len(never), len(set(never) & set(pv))))
