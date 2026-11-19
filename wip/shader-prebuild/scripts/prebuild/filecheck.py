"""filecheck.py PREP TRAIN.bin TEST.bin: what a precompiled file holds of the test cache's pipelines that training lacked."""
import sys, struct, collections
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0, REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py')
import lichii_cache as lc, state_model_static as st
data = open(sys.argv[1], 'rb').read()
magic, version, env_count, record_count, _ = struct.unpack_from('<8sIIII', data, 0)
off = 24 + 16 * env_count
keys, frag, vert, pairs, ncomp = set(), set(), set(), set(), 0
def sides(key):
    hs = struct.unpack_from('<6Q', key, 0); s = st.canonical(key[48:48 + 432]); t, l, f, d, sc = st.parts(s)
    return hs, s, (hs[5], f), (hs[:5], t, l)
for _ in range(record_count):
    kind, count, _ = struct.unpack_from('<BBH', data, off); off += 4 + 4 * count
    if kind == 1: ncomp += 1; off += 24; continue
    hs, s, fk, vk = sides(data[off:off + 1056]); off += 1056
    keys.add((hs, s)); frag.add(fk); vert.add(vk); pairs.add(hs)
print(f"file: {record_count} records, {ncomp} compute, {len(keys)} graphics keys, {len(frag)} fragment (shader, target state), {len(vert)} vertex-side (shaders, topology, layout)")
def load(p):
    out = {}
    _, recs = lc.parse_cache(open(p, 'rb').read(), mesh_fields=True)
    for r in recs:
        if r.is_compute or lc.fps_size(r.key[48:]) != 432: continue
        hs, s, fk, vk = sides(r.key); out[(hs, s)] = (fk, vk, any(e.stage in (7, 8) for e in r.envs))
    return out
tr, te = load(sys.argv[2]), load(sys.argv[3])
trf, trv = {x[0] for x in tr.values()}, {x[1] for x in tr.values()}
for name, sel in (('vertex+pixel', False), ('mesh', True)):
    new = {k: v for k, v in te.items() if k not in tr and v[2] == sel}
    n = len(new) or 1
    fnew = {v[0] for v in new.values()} - trf; vnew = {v[1] for v in new.values()} - trv
    print(f"{name}: test pipelines not in training {len(new)}")
    print(f"   exact key in file {sum(k in keys for k in new)} ({sum(k in keys for k in new)/n:.0%}); shader set in file {sum(k[0] in pairs for k in new)/n:.0%}")
    print(f"   fragment side in file {sum(v[0] in frag for v in new.values())/n:.0%}; vertex side in file {sum(v[1] in vert for v in new.values())/n:.0%}; both {sum(v[0] in frag and v[1] in vert for v in new.values())/n:.0%}")
    print(f"   distinct NEW fragment compiles Metal needs (shader, target state not in training): {len(fnew)}, in file {len(fnew & frag)} ({len(fnew & frag)/(len(fnew) or 1):.0%})")
    print(f"   distinct NEW vertex-side compiles: {len(vnew)}, in file {len(vnew & vert)} ({len(vnew & vert)/(len(vnew) or 1):.0%})")
