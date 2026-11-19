"""Sorts the precompiled-file builder's unexplained counts by cause (precompiled-file.md).

usage: python3.14 -I unexplained_counts.py LICHII_PY_DIR OUT_DIR cache.bin [cache.bin ...]
OUT_DIR holds scan.tsv, scan.envs, inventory.json, nx_pairs.json, mesh_combos.json, mesh.mesh,
mesh_draws.tsv. Prints (1) the scan's not-ok programs by status, stage, reason and file, and the
caches' drawn programs among them; (2) the pairs without an oracle environment; (3) the mesh draws
without environments.
"""
import collections
import json
import re
import struct
import sys

sys.path.insert(0, sys.argv[1])
import lichii_cache as lc  # noqa: E402

out = sys.argv[2]
caches = sys.argv[3:]
STAGE = {0: 'VertexA', 1: 'VertexB', 2: 'TessCtl', 3: 'TessEval', 4: 'Fragment', 5: 'Geometry',
         6: 'Compute', 7: 'Task', 8: 'Mesh'}

rows = []
with open(out + '/scan.tsv') as f:
    head = f.readline().rstrip('\n').split('\t')
    for line in f:
        rows.append(dict(zip(head, line.rstrip('\n').split('\t'))))
inv = json.load(open(out + '/inventory.json'))
assert len(inv) == len(rows)
for r, i in zip(rows, inv):
    assert r['index'] == str(i['index']) and r['stage'] == i['stage']
    r['source'], r['coarse'], r['left_out'] = i['source'], i['coarse'], i['left_out']

# Hashes the caches drew, by stage.
drawn = collections.defaultdict(set)
drawn_in = collections.defaultdict(set)
for path in caches:
    _, recs = lc.parse_cache(open(path, 'rb').read(), mesh_fields=True)
    for rec in recs:
        for e in rec.envs:
            h = '%016x' % lc.native_shader_hash(e.code)
            drawn[h].add(STAGE.get(e.stage, e.stage))
            drawn_in[h].add(path.split('/')[-1])
ok_hashes = {r['code_hash'] for r in rows if r['status'] == 'ok'}
any_hashes = {r['code_hash'] for r in rows if r['code_hash'] != '0' * 16}

bad = [r for r in rows if r['status'] != 'ok']
print('== 1. not-ok programs', len(bad))
by = collections.Counter((r['status'], r['stage']) for r in bad)
for k, n in sorted(by.items(), key=lambda x: -x[1]):
    print('  %-16s %-9s %4d' % (k[0], k[1], n))
print('  -- capture failures by reason (offset stripped) and stage')
reason = collections.Counter((re.sub(r' at 0x[0-9a-f]+', '', r['error']), r['stage'])
                             for r in bad if r['status'] == 'capture')
for k, n in sorted(reason.items(), key=lambda x: -x[1]):
    print('  %4d  %-9s %s' % (n, k[1], k[0]))
print('  -- capture failures by shader file (left_out = in a version the game does not load)')
files = collections.Counter((r['coarse'], r['left_out']) for r in bad if r['status'] == 'capture')
for k, n in sorted(files.items(), key=lambda x: -x[1]):
    print('  %4d  %s%s' % (n, k[0], '  [left out]' if k[1] else ''))
print('  -- mesh-hash-only by file')
files = collections.Counter((r['coarse'], r['left_out']) for r in bad if r['status'] == 'mesh-hash-only')
for k, n in sorted(files.items(), key=lambda x: -x[1])[:12]:
    print('  %4d  %s%s' % (n, k[0], '  [left out]' if k[1] else ''))
print('  (%d files in all)' % len(files))
mho = {r['code_hash'] for r in bad if r['status'] == 'mesh-hash-only'}
print('  mesh-hash-only programs the caches drew:', len(mho & set(drawn)),
      collections.Counter(s for h in mho & set(drawn) for s in drawn[h]))
unmatched = {h: s for h, s in drawn.items() if h not in any_hashes}
print('  drawn programs whose hash no scanned program has (would be the capture failures):',
      len(unmatched), dict(collections.Counter(s for v in unmatched.values() for s in v)))
for h, s in sorted(unmatched.items()):
    print('    ', h, sorted(s), sorted(drawn_in[h]))
nonmesh_unmatched = {h for h, s in drawn.items() if h not in ok_hashes and not s <= {'Task', 'Mesh'}}
print('  drawn non-mesh programs without an ok scan row:', len(nonmesh_unmatched))

# Oracle environments, as build_precompiled reads them.
oracle = set()
data = open(out + '/scan.envs', 'rb').read()
o = 8
while o < len(data):
    _, code_hash, size = struct.unpack_from('<IQI', data, o)
    oracle.add('%016x' % code_hash)
    o += 16 + size
by_hash = collections.defaultdict(list)
for r in rows:
    by_hash[r['code_hash']].append(r)

# Variations (game.variations.tsv: origin, then its programs' fingerprints): which programs failed
# lowering where a pair or combination names hash 0 (game_tables.py pairs every member, and a
# program that failed lowering has code_hash 0).
by_skey = {}
for r, i in zip(rows, inv):
    by_skey[i['skey']] = r
variations = []
with open(out + '/game.variations.tsv') as f:
    for line in f:
        origin, *fps = line.rstrip('\n').split('\t')
        variations.append((origin, [by_skey[x] for x in fps if x in by_skey]))
ZERO = '0' * 16


def zero_members(known, stage):
    """The failed programs of `stage` in variations that hold every hash in `known`."""
    found = collections.Counter()
    for origin, members in variations:
        hs = {m['code_hash'] for m in members}
        if not all(k in hs for k in known):
            continue
        for m in members:
            if m['code_hash'] == ZERO and m['stage'] == stage:
                found[(m['source'], m['error'])] += 1
    return found


def describe(h):
    if h == ZERO:
        return 'hash 0 = a program that failed lowering (no hash)'
    rs = by_hash.get(h)
    if not rs:
        return '%s not in scan%s' % (h, ' (drawn: %s)' % sorted(drawn[h]) if h in drawn else '')
    r = rs[0]
    return '%s %s %s %s%s' % (h, r['stage'], r['status'], r['source'], ' (drawn)' if h in drawn else '')

pairs = {tuple(p) for p in json.load(open(out + '/nx_pairs.json'))}
print('\n== 2. pairs without an oracle environment (nx_pairs.json; recorded pairs come from caches)')
n = 0
for vh, fh in sorted(pairs):
    if vh in oracle and fh in oracle:
        continue
    n += 1
    print('  pair', n)
    for h, side in ((vh, 'vertex'), (fh, 'pixel')):
        print('    %-6s %s%s' % (side, describe(h), '' if h in oracle else '  <- no oracle'))
    known = [h for h in (vh, fh) if h != ZERO]
    for (src, err), k in zero_members(known, 'Fragment' if fh == ZERO else 'VertexB').items():
        print('      failed member: %s: %s' % (src, err))
print('  total', n)

print('\n== 3. mesh draws without environments (mesh_combos.json)')
draws = set()
data = open(out + '/mesh.mesh', 'rb').read()
o = 8
while o < len(data):
    _, _, task, mesh = struct.unpack_from('<IQQQ', data, o)
    o += 28
    (ts,) = struct.unpack_from('<I', data, o)
    o += 4 + ts
    (ms,) = struct.unpack_from('<I', data, o)
    o += 4 + ms
    draws.add((task, mesh))
mesh_rows = {}
with open(out + '/mesh_draws.tsv') as f:
    for line in f:
        parts = line.rstrip('\n').split(' ')
        if len(parts) >= 2:
            mesh_rows.setdefault(parts[1], line.strip())
n = 0
why = collections.Counter()
for task_h, mesh_h, pixel_h in json.load(open(out + '/mesh_combos.json')):
    task, mesh = int(task_h, 16) if task_h else 0, int(mesh_h, 16)
    miss = []
    if pixel_h not in oracle:
        miss.append('pixel has no oracle')
    if (task, mesh) not in draws:
        miss.append('(task, mesh) not in mesh.mesh')
    if not miss:
        continue
    n += 1
    why[tuple(miss)] += 1
    print('  draw', n, ', '.join(miss))
    for h, side in ((task_h, 'task'), (mesh_h, 'mesh'), (pixel_h, 'pixel')):
        if h:
            print('    %-5s %s' % (side, describe(h)))
    known = [h for h in (task_h, mesh_h, pixel_h) if h and h != ZERO]
    for h, stage in ((mesh_h, 'Mesh'), (pixel_h, 'Fragment')):
        if h == ZERO:
            for (src, err), k in zero_members(known, stage).items():
                print('      failed %s member: %s: %s' % (stage, src, err))
    if mesh_h != ZERO and (task, mesh) not in draws:
        print('      mesh program in mesh_draws.tsv:', mesh_rows.get(mesh_h, 'no row'))
print('  total', n, dict(why))
