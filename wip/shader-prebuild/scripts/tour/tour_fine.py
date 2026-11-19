import json, collections, pickle
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
O=REPO + '/wip/shader-prebuild/local/emulator-prebuild/eval/out-all'
inv=json.load(open(O+'/inventory.json'))
fine=collections.defaultdict(set); coarse=collections.defaultdict(set)
for r in inv: fine[r['code_hash']].add(r['fine']); coarse[r['code_hash']].add(r['coarse'])
pairs=set(tuple(p) for p in json.load(open(O+'/nx_pairs.json')))
S=pickle.load(open('seen.pkl','rb')); allseen=set().union(*S['seen'].values())
for big in ['/Shader/Model.Product.110.product.Nin_Ounce_NVN2.bfsha.zs','/Effect/static.Nin_Ounce_NVN2.vsetb.byml.zs','/Lib/agl/agl_resource.Nin_Ounce_NVN2.release.sarc.zs/agl_technique_pfx.sharcb']:
    G=collections.defaultdict(lambda:[0,0])
    for p in pairs:
        if big in coarse.get(p[0],()):
            g=sorted(fine[p[0]])[0]; G[g][0]+=1; G[g][1]+= p in allseen
    gs=sorted(G.values(),key=lambda x:-x[0])
    print(big[-60:], 'groups',len(G),'groups seen',sum(1 for x in gs if x[1]), 'top', gs[:8])
    seen_groups=[x for x in gs if x[1]]
    print('  pairs in seen groups',sum(x[0] for x in seen_groups),'seen',sum(x[1] for x in seen_groups))
# How many pairs per cache are new vs previous caches (saturation)
s=S['seen']; a=s[1]; b=s[2]; c=s[3]
print('cache sizes',len(a),len(b),len(c),'a&b',len(a&b),'a&c',len(a&c),'b&c',len(b&c),'union',len(a|b|c))
