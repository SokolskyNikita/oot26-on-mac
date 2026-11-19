import json, collections, pickle
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
O=REPO + '/wip/shader-prebuild/local/emulator-prebuild/eval/out-all'
inv=json.load(open(O+'/inventory.json'))
coarse=collections.defaultdict(set)
for r in inv: coarse[r['code_hash']].add(r['coarse'])
pairs=set(tuple(p) for p in json.load(open(O+'/nx_pairs.json')))
S=pickle.load(open('seen.pkl','rb')); seen=S['seen']; allseen=set().union(*seen.values())
per=pickle.load(open('prep_per_pair.pkl','rb'))
def fileof(p):
    v,f=p; c=coarse.get(v) or coarse.get(f) or {'?'}
    return sorted(c)[0], len(c)
amb=sum(1 for p in pairs if fileof(p)[1]>1); print('pairs whose vertex shader is in >1 file',amb)
# do vertex & pixel share file?
same=sum(1 for p in pairs if coarse.get(p[0]) and coarse.get(p[1]) and coarse[p[0]]&coarse[p[1]]); print('pairs with vs/fs in same file',same, 'of',len(pairs))
F=collections.defaultdict(lambda: dict(pairs=0,seen=0,recs=0,recs_seen=0))
for p in pairs|set(per):
    fn,_=fileof(p); d=F[fn]
    if p in pairs: d['pairs']+=1
    d['recs']+=per.get(p,0)
    if p in allseen: d['seen']+=1; d['recs_seen']+=per.get(p,0)
files=[f for f in F if F[f]['pairs']]
print('files',len(files),'files with any seen',sum(1 for f in files if F[f]['seen']))
print('total pairs',sum(F[f]['pairs'] for f in files),'vp records',sum(F[f]['recs'] for f in F))
# distinct recorded keys per seen pair
keys=collections.Counter((v,f) for v,f,k in S['keys'])
print('distinct recorded vp keys',len(S['keys']),'per seen pair mean',len(S['keys'])/len(allseen))
# top files by pairs
top=sorted(files,key=lambda f:-F[f]['pairs'])
print('\nlargest files: pairs seen recs')
for f in top[:15]: print(F[f]['pairs'],F[f]['seen'],F[f]['recs'],f[-90:])
print('\nseen files: pairs seen frac recs')
sf=sorted([f for f in files if F[f]['seen']],key=lambda f:-F[f]['seen'])
for f in sf[:40]: d=F[f]; print(d['pairs'],d['seen'],'%.2f'%(d['seen']/d['pairs']),d['recs'],f[-80:])
# category by top dir
cat=collections.defaultdict(lambda:[0,0,0,0])
for f in files:
    c=f.split('/')[1] if f.startswith('/') else f
    x=cat[c]; x[0]+=1; x[1]+=F[f]['pairs']; x[2]+=F[f]['seen']; x[3]+=1 if F[f]['seen'] else 0
print('\ncategory files pairs seenpairs seenfiles')
for c,x in sorted(cat.items(),key=lambda t:-t[1][1]): print(c,x)
pickle.dump(dict((f,F[f]) for f in F),open('perfile.pkl','wb'))
