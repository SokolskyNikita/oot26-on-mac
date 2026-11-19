"""variants_in_cache.py: how many graphics pipelines Lichii's cache holds per fragment program, and what differs
between pipelines that share one. Reads the cache only. Usage: python3 variants_in_cache.py [CACHE.bin]
The pipeline key is the last 1056 bytes of a Graphics record: six program hashes, then FixedPipelineState
(renderer_vulkan/fixed_pipeline_state.h)."""
import sys, struct, collections, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../extractor/shaders'))
import lichii_cache as lc
path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin')
latest, counts = lc.load(path)
print(dict(counts))
progs = {}
for (k, key), v in latest.items():
    if k == 1:
        p = lc.program(v); progs[p['unique_hash']] = p
FIELDS = [(0, 4, 'raw1: topology/msaa/dynamic-state flags'), (4, 8, 'raw2: depth format/alpha test/early-z'),
          (8, 16, 'colour formats'), (16, 24, 'driver id/version'), (24, 32, 'alpha ref/point size'),
          (32, 64, 'viewport swizzles'), (64, 72, 'vertex attribute types'), (72, 80, 'dynamic: cull/depth/stencil'),
          (80, 112, 'blend attachments'), (112, 240, 'vertex attributes'), (240, 368, 'binding divisors'),
          (368, 432, 'vertex strides'), (432, 1008, 'xfb/depth bounds/stipple')]
def size(st):
    raw1 = struct.unpack_from('<I', st, 0)[0]
    xfb, dvi, eds, eds3b = raw1 >> 6 & 1, raw1 >> 5 & 1, raw1 & 1, raw1 >> 3 & 1
    if xfb: return 1008
    if dvi and eds3b: return 80
    if dvi: return 112
    if eds: return 368
    return 432
pipes = []
for (k, key), v in latest.items():
    if k != 2: continue
    kb = v[-1056:]
    hs = struct.unpack_from('<6Q', kb, 0)
    pipes.append((hs, kb[48:]))
flags = collections.Counter()
for hs, st in pipes:
    raw1 = struct.unpack_from('<I', st, 0)[0]
    flags[(raw1 & 1, raw1 >> 1 & 1, raw1 >> 3 & 1, raw1 >> 4 & 1, raw1 >> 5 & 1, size(st))] += 1
print('dynamic-state flags (eds, eds2, eds3_blend, eds3_enables, dyn_vertex_input, compared bytes):', dict(flags))
slots = collections.Counter(tuple(i for i, h in enumerate(hs) if h) for hs, _ in pipes)
print('program slots filled:', dict(slots))
known = sum(1 for hs, _ in pipes if hs[5] in progs)
print(f'pipelines {len(pipes)}, with slot-5 hash a known Program record: {known}')
by_fs = collections.defaultdict(list)
for hs, st in pipes: by_fs[hs[5]].append((hs, st))
hist = collections.Counter(len(v) for v in by_fs.values())
print(f'distinct fragment programs (slot 5): {len(by_fs)}  mean pipelines each: {len(pipes)/len(by_fs):.2f}')
print('pipelines per fragment program -> number of fragment programs:')
buckets = [(1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 32), (33, 10**9)]
for lo, hi in buckets:
    n = sum(c for k, c in hist.items() if lo <= k <= hi); m = sum(k * c for k, c in hist.items() if lo <= k <= hi)
    print(f'  {lo}-{hi if hi < 10**9 else "..."}: {n} programs, {m} pipelines')
print('top:', sorted(((len(v), f'{k:016x}') for k, v in by_fs.items()), reverse=True)[:6])
# what differs inside a group
why = collections.Counter(); combos = collections.Counter()
extra = 0
for fs, group in by_fs.items():
    if len(group) < 2: continue
    extra += len(group) - 1
    n = min(size(st) for _, st in group)
    diff = set()
    if len({hs[:5] for hs, _ in group}) > 1: diff.add('other stages (vertex/mesh/...)')
    for lo, hi, name in FIELDS:
        if lo >= n: break
        if len({st[lo:min(hi, n)] for _, st in group}) > 1: diff.add(name)
    for d in diff: why[d] += 1
    combos[tuple(sorted(diff))] += len(group) - 1
print(f'pipelines beyond the first for their fragment program: {extra} of {len(pipes)}')
print('fragment programs with >1 pipeline, by what varies (a program can count in several):')
for k, c in why.most_common(): print(f'  {c:4d}  {k}')
print('extra pipelines by exact combination of what varies:')
for k, c in combos.most_common(10): print(f'  {c:4d}  {" + ".join(k) or "(nothing inside the compared bytes)"}')
# distinct (fragment program, state relevant to fragment code on Apple GPUs: colour formats + blend + msaa + alpha test)
def fragkey(hs, st):
    raw1, raw2 = struct.unpack_from('<II', st, 0)
    return (hs[5], st[8:16], st[80:112] if size(st) > 80 else b'', raw1 >> 28, raw2 >> 1 & 7, raw2 >> 15 & 3)
print('distinct (fragment program, colour formats, blend if in key, msaa, alpha test):', len({fragkey(*p) for p in pipes}))
print('distinct (fragment program, vertex-side stages):', len({hs for hs, _ in pipes}))
