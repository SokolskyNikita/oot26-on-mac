import pickle
F=pickle.load(open('perfile.pkl','rb'))
files={f:d for f,d in F.items() if d['pairs']}
tot_pairs=sum(d['pairs'] for d in files.values()); tot_recs=sum(d['recs'] for d in F.values())
print('pairs',tot_pairs,'vp records now',tot_recs, 'records/pair %.2f'%(tot_recs/tot_pairs))
REC_VP=4041; MESH=6209; COMP=4058
for big in (None,1000,200,50):
  for minseen in (1,2):
    ex=[f for f,d in files.items() if d['seen']>=minseen and (big is None or d['pairs']<=big)]
    unseen_in_ex=sum(files[f]['pairs']-files[f]['seen'] for f in ex)
    unex=[f for f in files if f not in ex]
    unseen_unex=sum(files[f]['pairs']-files[f]['seen'] for f in unex)
    full_recs_unex=sum(files[f]['recs']-files[f]['recs_seen'] for f in unex)
    print(f'big<= {big} minseen {minseen}: exercised files {len(ex)}, unseen pairs dropped {unseen_in_ex}, unseen pairs kept {unseen_unex}; '
          f'records with 1/pair: {REC_VP+MESH+COMP+unseen_unex}; with full prediction kept: {REC_VP+MESH+COMP+full_recs_unex}')
# share of unseen pairs in the five big shared files
big5=sorted(files,key=lambda f:-files[f]['pairs'])[:8]
print('top8 files unseen pairs', sum(files[f]['pairs']-files[f]['seen'] for f in big5))
eff=[f for f in files if f.startswith('/Effect/')]
print('effect files',len(eff),'pairs',sum(files[f]['pairs'] for f in eff),'median pairs', sorted(files[f]['pairs'] for f in eff)[len(eff)//2])
import collections
pre=collections.Counter()
for f in eff:
    n=f.split('/')[-1].split('.')[0]; p=n.split('_')[0]; pre[p]+=files[f]['pairs']
print(pre.most_common(15))
