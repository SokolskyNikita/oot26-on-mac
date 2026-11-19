"""eval_static.py INVENTORY TRAIN.bin[,TRAIN2.bin] TEST.bin: held-out accuracy of state_model_static."""
import sys, json, collections
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0, REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py')
import lichii_cache as lc, statefields as sf, state_model as sm, state_model_static as st
inv = json.load(open(sys.argv[1])); by = {}
for r in inv: by.setdefault(r['code_hash'], r)
def info(env, vertex):
    h = '%016x' % lc.native_shader_hash(env.code); row = by.get(h, {})
    d = dict(hash=h, fine=row.get('fine', '?'), coarse=row.get('coarse', '?'))
    if vertex: d['read_mask'] = sf.attribute_read_mask(env.sph)
    else: d['pclass'] = sm.pixel_class(env.sph)
    return d
def pipes(paths):
    out = {}
    for path in paths.split(','):
        _, recs = lc.parse_cache(open(path, 'rb').read(), mesh_fields=True)
        for r in recs:
            if r.is_compute or len(r.envs) != 2 or r.envs[0].stage != 0 or r.envs[-1].stage != 4: continue
            if lc.fps_size(r.key[48:]) != 432: continue
            v, f = info(r.envs[0], True), info(r.envs[-1], False); s = st.canonical(r.key[48:])
            out[(v['hash'], f['hash'], s)] = (v, f, s)
    return out
tr, te = pipes(sys.argv[2]), pipes(sys.argv[3])
new = [x for k, x in te.items() if k not in tr]
m = st.Model()
for v, f, s in tr.values(): m.add(v, f, s)
sv, sf_, sp = {v['hash'] for v, _, _ in tr.values()}, {f['hash'] for _, f, _ in tr.values()}, {(v['hash'], f['hash']) for v, f, _ in tr.values()}
# what Metal compiled for the training pipelines: fragment (shader, F) and vertex (shader, T, L)
print(f"train pipelines {len(tr)}, test {len(te)}, test not in train {len(new)}")
for K in ((1,1,1,1), (2,3,4,2), (2,4,6,3), (3,6,8,4)):
    kt, kl, kf, kd = K
    c = collections.Counter(); bycat = collections.defaultdict(collections.Counter)
    for v, f, s in new:
        t, l, ff, d, ss = st.parts(s)
        ct, cl, cf, cd, cs = m.part_candidates(v, f, kt, kl, kf, kd)
        cat = ('pair seen' if (v['hash'], f['hash']) in sp else 'both shaders seen' if v['hash'] in sv and f['hash'] in sf_ else
               'pixel new' if v['hash'] in sv else 'vertex new' if f['hash'] in sf_ else 'both new')
        hit = dict(T=t in ct, L=l in cl, F=ff in cf, D=d in cd, S=ss in cs)
        key = s in m.candidates(v, f, kt, kl, kf, kd)
        b = bycat[cat]; b['n'] += 1
        for k_, h in hit.items(): b[k_] += h
        b['frag warm (F)'] += hit['F']; b['vert warm (T,L)'] += hit['T'] and hit['L']; b['both warm'] += hit['F'] and hit['T'] and hit['L']; b['key'] += key
    tot = collections.Counter()
    for b in bycat.values(): tot.update(b)
    print(f"\nk: T{kt} L{kl} F{kf} D{kd}   candidates per pair <= {1+(kf-1)+(kl-1)+(kd-1)+(kt-1)}")
    for cat, b in list(sorted(bycat.items())) + [('ALL', tot)]:
        n = b['n']
        print(f"  {cat:18} n {n:5}  T {b['T']/n:4.0%} L {b['L']/n:4.0%} F {b['F']/n:4.0%} D {b['D']/n:4.0%} S {b['S']/n:4.0%} | frag warm {b['frag warm (F)']/n:4.0%}  vert warm {b['vert warm (T,L)']/n:4.0%}  both {b['both warm']/n:4.0%}  exact key {b['key']/n:4.0%}")
