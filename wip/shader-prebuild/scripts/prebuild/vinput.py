"""vinput.py INVENTORY TRAIN.bin TEST.bin: how predictable the vertex-input part of non-DVI keys is."""
import sys, os, json, struct, collections
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0, REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py')
import lichii_cache as lc, statefields as sf
inv = json.load(open(sys.argv[1])); by = {}
for r in inv: by.setdefault(r['code_hash'], r)
def canon_vi(st, mask, n):
    """attributes [112:240], divisors [240:368], strides [368:432]; clear what unread attributes bring."""
    att = list(struct.unpack_from('<32I', st, 112)); div = list(struct.unpack_from('<32I', st, 240))
    strides = list(struct.unpack_from('<32H', st, 368)) if n >= 432 else [0]*32
    used = set()
    for i in range(32):
        if not (mask >> i & 1) or not att[i] & 1: att[i] = 0
        else: used.add(att[i] >> 1 & 31)
    for b in range(32):
        if b not in used: div[b] = 0; strides[b] = 0
    return (tuple(att), tuple(div), tuple(strides))
def load(path):
    _, recs = lc.parse_cache(open(path, 'rb').read(), mesh_fields=True)
    out = {}; flags = collections.Counter(); kinds = collections.Counter()
    for r in recs:
        if r.is_compute: kinds['compute'] += 1; continue
        st = r.key[48:]; raw1 = sf.u32(st, 0); n = lc.fps_size(st)
        flags[(raw1 & 0x3f, n)] += 1
        if r.envs[0].stage != 0 or r.envs[-1].stage != 4: kinds['mesh/other'] += 1; continue
        kinds['vs+fs'] += 1
        vh = '%016x' % lc.native_shader_hash(r.envs[0].code); fh = '%016x' % lc.native_shader_hash(r.envs[-1].code)
        mask = sf.attribute_read_mask(r.envs[0].sph)
        raw = st[112:n]; can = canon_vi(st, mask, n)
        base = sf.canonical(st[:112], None)
        out[(vh, fh, st[:n])] = dict(vh=vh, fh=fh, raw=raw, can=can, base=base, mask=mask, row=by.get(vh, {}))
    return list(out.values()), flags, kinds
tr, fl, k = load(sys.argv[2]); print('train', len(tr), dict(k), 'flags(raw1&63,size):', dict(fl))
te, fl, k = load(sys.argv[3]); print('test ', len(te), dict(k), 'flags:', dict(fl))
for name, S in (('train', tr), ('test', te)):
    pv = collections.defaultdict(set); pvr = collections.defaultdict(set)
    for x in S: pv[x['vh']].add(x['can']); pvr[x['vh']].add(x['raw'])
    h = collections.Counter(min(len(v), 5) for v in pv.values()); hr = collections.Counter(min(len(v), 5) for v in pvr.values())
    print(f"{name}: vertex shaders {len(pv)}; layouts per shader canonical {dict(sorted(h.items()))} raw {dict(sorted(hr.items()))}; distinct layouts overall canonical {len({x['can'] for x in S})} raw {len({x['raw'] for x in S})}")
    print(f"   distinct masks {len({x['mask'] for x in S})}; (mask->layouts) max {max(len(v) for v in collections.defaultdict(set, {m: {x['can'] for x in S if x['mask']==m} for m in {x['mask'] for x in S}}).values())}")
# held out
seen = {x['vh'] for x in tr}
new = [x for x in te if x['vh'] not in seen]
own = collections.defaultdict(collections.Counter); lv = {l: collections.defaultdict(collections.Counter) for l in ('fine', 'coarse', 'mask', 'global')}
for x in tr:
    own[x['vh']][x['can']] += 1
    lv['fine'][(x['row'].get('fine'), x['mask'])][x['can']] += 1; lv['coarse'][(x['row'].get('coarse'), x['mask'])][x['can']] += 1
    lv['mask'][x['mask']][x['can']] += 1; lv['global'][0][x['can']] += 1
def cands(x, k):
    c = []
    for l, key in (('fine', (x['row'].get('fine'), x['mask'])), ('coarse', (x['row'].get('coarse'), x['mask'])), ('mask', x['mask'])):
        for lay, _ in lv[l].get(key, collections.Counter()).most_common(k):
            if lay not in c: c.append(lay)
    return c[:k]
print(f"test pipelines whose vertex shader is new: {len(new)} of {len(te)}; in inventory: {sum(1 for x in new if x['row'])}")
for k in (1, 2, 4, 8):
    print(f"  layout among top-{k} candidates (fine+mask, coarse+mask, mask): {sum(1 for x in new if x['can'] in cands(x, k))}")
old = [x for x in te if x['vh'] in seen and (x['vh'], x['fh'], x['raw'], x['base']) not in {(y['vh'], y['fh'], y['raw'], y['base']) for y in tr}]
print(f"test pipelines new but with a seen vertex shader: {len(old)}; layout already seen for that shader: {sum(1 for x in old if x['can'] in own[x['vh']])}")
