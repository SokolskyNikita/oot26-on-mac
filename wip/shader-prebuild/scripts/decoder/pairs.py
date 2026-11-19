import sys, json, struct, collections, re, pickle
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0,REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py')
import lichii_cache as lc
O=REPO + '/wip/shader-prebuild/local/emulator-prebuild/eval/out-all/'
inv=json.load(open(O+'inventory.json')); by_fp={r['skey']:r for r in inv}
nxp=set(map(tuple,json.load(open(O+'nx_pairs.json'))))
# pairs per variation
var_pairs={}  # label -> set of (v,p) code hashes
pair_labels=collections.defaultdict(set)
for line in open(O+'game.variations.tsv'):
    label,*fps=line.rstrip('\n').split('\t')
    ms=[by_fp[f] for f in fps if f in by_fp]
    if any(m['left_out'] for m in ms): continue
    vs=[m['code_hash'] for m in ms if m['stage']=='VertexB']; ps=[m['code_hash'] for m in ms if m['stage']=='Fragment']
    for v in vs:
        for p in ps: pair_labels[(v,p)].add(label)
def fam(f):
    f=f.split('#')[0]
    if f.startswith('/Effect/'): return 'Effect/*.vsetb'
    if f.startswith('/Shader/') and '.bfsha' in f: return f.split('/')[-1].split('.product')[0]
    if 'ApplicationPackage' in f: return 'ApplicationPackage SARC: '+f.split('/')[-1] if '.bfsha' in f else 'ApplicationPackage SARC (sharcb)'
    if f.startswith('/Lib/'): return 'Lib/'+f.split('/')[2]+' (sharcb)'
    return '/'.join(f.split('/')[:2])+'/…'
fp=collections.Counter(); 
# assign each nx pair to all families containing it
famsets=collections.defaultdict(set)
for pr,labs in pair_labels.items():
    for l in labs: famsets[fam(l)].add(pr)
used_pairs=set()
for c in ['cache1','cache2','cache3']:
    _,recs=lc.parse_cache(open(O+c+'.fork-v54.bin','rb').read(),mesh_fields=True)
    for r in recs:
        if r.is_compute: continue
        uh=struct.unpack_from('<6Q',r.key,0)
        if uh[1] and uh[5]: used_pairs.add(('%016x'%uh[1],'%016x'%uh[5]))
print('nx pairs',len(nxp),'pairs w/ labels',len(pair_labels),'cache graphics pairs',len(used_pairs),'of which in nx',len(used_pairs&nxp))
rows=[]
for k,s in famsets.items(): rows.append((len(s),len(s&used_pairs),k))
for n,u,k in sorted(rows,reverse=True): print(f'{n:7d} {u:6d} {k}')
mp=[(pr,labs) for pr,labs in pair_labels.items() if any('Model.Product.110' in l for l in labs)]
pickle.dump({'used':used_pairs,'model110':mp},open(sys.argv[1],'wb'))
