import sys, json, collections, pickle
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
PY=REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py'
O=REPO + '/wip/shader-prebuild/local/emulator-prebuild/eval/out-all'
sys.path.insert(0, PY)
import lichii_cache as lc
inv=json.load(open(O+'/inventory.json'))
coarse=collections.defaultdict(set); stage={}
for r in inv:
    coarse[r['code_hash']].add(r['coarse']); stage[r['code_hash']]=r['stage']
pairs=set(tuple(p) for p in json.load(open(O+'/nx_pairs.json')))
seen=collections.defaultdict(set)  # cache -> pairs
seen_states=collections.Counter()   # pair -> distinct recorded keys
nrec=collections.Counter()
for i in (1,2,3):
    _, recs = lc.parse_cache(open(O+'/cache%d.fork-v54.bin'%i,'rb').read(), mesh_fields=True)
    for rec in recs:
        if rec.is_compute: nrec[(i,'compute')]+=1; continue
        st=[e.stage for e in rec.envs]
        if st==[0,4] or (len(rec.envs)==2 and rec.envs[0].stage==0 and rec.envs[-1].stage==4):
            vh='%016x'%lc.native_shader_hash(rec.envs[0].code); fh='%016x'%lc.native_shader_hash(rec.envs[-1].code)
            seen[i].add((vh,fh)); nrec[(i,'vp')]+=1
            seen_states[(vh,fh,bytes(rec.key))]+=1
        else:
            nrec[(i,'other:'+','.join(map(str,st)))]+=1
pickle.dump(dict(seen=dict(seen), keys=list(seen_states), nrec=nrec), open('seen.pkl','wb'))
print(nrec)
allseen=set().union(*seen.values())
print('seen pairs', len(allseen), 'in nx_pairs', len(allseen & pairs))
