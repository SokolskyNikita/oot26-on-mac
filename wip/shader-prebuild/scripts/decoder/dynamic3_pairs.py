"""Vertex/pixel pairs that only `gsys_assign_dynamic3` programs use, for build_precompiled.py --drop-pairs.

A pair is listed when every shader variation that holds it (game.variations.tsv, left-out files
skipped as game_tables.py does) is a program of a Model.Product.110 shading model whose dynamic
option gsys_assign_type is dynamic3. Pairs drawn in any training cache are never listed.

usage: python3 -I dynamic3_pairs.py Model.Product.110.product.Nin_Ounce_NVN2.bfsha OUT_DIR drop.json
  OUT_DIR holds inventory.json, game.variations.tsv, nx_pairs.json and cache*.fork-v54.bin
"""
import collections
import glob
import json
import mmap
import os
import struct
import sys

import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0, REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/'
                   'tools/nx2-precompile/py')
import lichii_cache as lc  # noqa: E402

bfsha, out_dir, dest = sys.argv[1:4]
f = open(bfsha, 'rb')
d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
u8 = lambda a: d[a]
u16 = lambda a: struct.unpack_from('<H', d, a)[0]
u32 = lambda a: struct.unpack_from('<I', d, a)[0]
u64 = lambda a: struct.unpack_from('<Q', d, a)[0]


def s(a):
    n = u16(a)
    return d[a + 2:a + 2 + n].decode()


def choices(opt):
    """Choice names of an option, in index order (dictionary nodes after the root)."""
    base, n = u64(opt + 8), u16(opt + 0x18)
    names = [s(u64(base + 8 + 16 * i + 8)) for i in range(n + 1)]
    return names[1:] if len(names) > n else names


# Per BNSH (by its offset, as the extractor's labels name it): variation -> pass name.
passes = {}
for smi in range(u16(0x78)):
    r = 0x80 + 0x100 * smi
    npg, sw, dw, nd = u16(r + 0xe8), u8(r + 0xea), u8(r + 0xeb), u16(r + 0xe6)
    bnsh = u64(r + 0xa8)
    g = bnsh + u16(bnsh + 0x16)
    vt = bnsh + u64(g + 0x20)
    progs, keys = u64(r + 0x88), u64(r + 0x90)
    dyn = {s(u64(q)): q for q in (u64(r + 0x18) + 0x28 * i for i in range(nd))}
    q = dyn['gsys_assign_type']
    mask, word, shift = u32(q + 0x20), u8(q + 0x24), u8(q + 0x25)
    names = choices(q)
    W = sw + dw
    var_pass = {}
    for p in range(npg):
        v, rem = divmod(u64(progs + 0x40 * p + 0x20) - vt, 0x40)
        assert rem == 0
        k = struct.unpack_from('<%dI' % W, d, keys + 4 * W * p)
        var_pass[v] = names[(k[word] & mask) >> shift]
    passes['BNSH@%#x' % bnsh] = var_pass
    print(s(u64(r)), 'BNSH@%#x' % bnsh, 'programs', npg, 'passes', dict(collections.Counter(var_pass.values())))

inv = json.load(open(os.path.join(out_dir, 'inventory.json')))
by_fp = {r['skey']: r for r in inv}
pair_passes = collections.defaultdict(set)   # pair -> passes, 'other' for a variation of another file
for line in open(os.path.join(out_dir, 'game.variations.tsv')):
    label, *fps = line.rstrip('\n').split('\t')
    ms = [by_fp[fp] for fp in fps if fp in by_fp]
    if any(m['left_out'] for m in ms):
        continue
    tag = 'other'
    if 'Model.Product.110' in label:
        bnsh, var = label.split('#')[1], int(label.split('#var')[1])
        tag = passes[bnsh][var]
    vs = [m['code_hash'] for m in ms if m['stage'] == 'VertexB']
    ps = [m['code_hash'] for m in ms if m['stage'] == 'Fragment']
    for v in vs:
        for p in ps:
            pair_passes[(v, p)].add(tag)

drawn = set()
for path in sorted(glob.glob(os.path.join(out_dir, 'cache*.fork-v54.bin'))):
    _, recs = lc.parse_cache(open(path, 'rb').read(), mesh_fields=True)
    for rec in recs:
        if not rec.is_compute:
            uh = struct.unpack_from('<6Q', rec.key, 0)
            drawn.add(('%016x' % uh[1], '%016x' % uh[5]))

nx_pairs = set(map(tuple, json.load(open(os.path.join(out_dir, 'nx_pairs.json')))))
dyn3 = [n for n in next(iter(passes.values())).values() if n.endswith('dynamic3')][:1]
assert dyn3, 'no dynamic3 choice'
only = sorted(pr for pr in nx_pairs if pair_passes.get(pr) == {dyn3[0]})
print('nx pairs', len(nx_pairs), 'with a variation', sum(pr in pair_passes for pr in nx_pairs))
print('Model.Product.110 pairs', sum(any(t != 'other' for t in pair_passes[pr]) for pr in nx_pairs if pr in pair_passes))
print('pairs only in %s programs' % dyn3[0], len(only), 'drawn among them', len(set(only) & drawn))
only = [pr for pr in only if pr not in drawn]
json.dump([list(pr) for pr in only], open(dest, 'w'))
print('wrote', len(only), 'pairs to', dest)
