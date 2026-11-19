import sys, struct, mmap, collections, pickle, json
P=pickle.load(open(sys.argv[2],'rb')); used=P['used']
f=open(sys.argv[1],'rb'); d=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
u8=lambda a:d[a]; u16=lambda a:struct.unpack_from('<H',d,a)[0]; u32=lambda a:struct.unpack_from('<I',d,a)[0]; u64=lambda a:struct.unpack_from('<Q',d,a)[0]
def s(a): n=u16(a); return d[a+2:a+2+n].decode()
SM={}
for smi in range(u16(0x78)):
    r=0x80+0x100*smi; npg=u16(r+0xe8); sw,dw=u8(r+0xea),u8(r+0xeb); no,nd=u16(r+0xe4),u16(r+0xe6)
    bnsh=u64(r+0xa8); g=bnsh+u16(bnsh+0x16); vt=bnsh+u64(g+0x20); progs=u64(r+0x88); keys=u64(r+0x90); W=sw+dw
    var2prog={}
    for p in range(npg): var2prog[(u64(progs+0x40*p+0x20)-vt)//0x40]=p
    K=[struct.unpack_from('<%dI'%W,d,keys+4*W*p) for p in range(npg)]
    dyn=[(s(u64(q)),u32(q+0x20),u8(q+0x24),u8(q+0x25)) for q in (u64(r+0x18)+0x28*i for i in range(nd))]
    SM['BNSH@%#x'%bnsh]=dict(name=s(u64(r)),var2prog=var2prog,K=K,sw=sw,dyn=dyn)
# per drawn pair, which (sm, program)
drawn_prog=collections.defaultdict(set); allpairs_static=collections.defaultdict(set)
for pr,labs in P['model110']:
    for l in labs:
        if 'Model.Product.110' not in l: continue
        b,v=l.split('#')[1],int(l.split('#var')[1]); sm=SM[b]; p=sm['var2prog'][v]
        sk=sm['K'][p][:sm['sw']]
        allpairs_static[(b,sk)].add(pr)
        if pr in used: drawn_prog[b].add(p)
for b,sm in SM.items():
    ps=drawn_prog[b]; sks=collections.Counter(sm['K'][p][:sm['sw']] for p in ps)
    allsk=collections.Counter(k[:sm['sw']] for k in sm['K'])
    print(sm['name'],'drawn programs',len(ps),'distinct static keys drawn',len(sks),'of',len(allsk))
    # for drawn static keys: how many of their programs drawn
    frac=[(sks[k],allsk[k]) for k in sks]
    print('  drawn/available programs per drawn static key, histogram:',sorted(collections.Counter(frac).items())[:15])
    # dynamic values among drawn programs
    for name,mask,w,sh in sm['dyn']:
        print('  dyn',name,'drawn values',sorted(collections.Counter((sm['K'][p][w]&mask)>>sh for p in ps).items()))
    # union of programs over drawn static keys -> pairs: precision proxy
    cand=[p for p,k in enumerate(sm['K']) if k[:sm['sw']] in sks]
    print('  programs sharing a drawn static key',len(cand))
# pair-level: pairs reachable from drawn static keys vs drawn pairs
cand_pairs=set(); 
dk={(b,sm['K'][p][:sm['sw']]) for b,ps in drawn_prog.items() for p in ps for sm in [SM[b]]}
for key in dk: cand_pairs|=allpairs_static[key]
dp={pr for pr,labs in P['model110'] if pr in used}
print('Model110 pairs drawn',len(dp),'pairs reachable from the drawn static keys',len(cand_pairs),'drawn among them',len(dp&cand_pairs))
print('total pairs per static key: mean', sum(len(v) for v in allpairs_static.values())/len(allpairs_static), 'max', max(len(v) for v in allpairs_static.values()))
print('---- dynamic combos per static key (model)')
sm=SM['BNSH@0xf7d000']; g=collections.defaultdict(list)
for p,k in enumerate(sm['K']):
    dv=tuple((k[w]&mask)>>sh for name,mask,w,sh in sm['dyn'])
    g[k[:sm['sw']]].append((dv[0],dv[2]))
print(collections.Counter(tuple(sorted(v)) for v in g.values()).most_common(4))
# pairs per program: how many programs share each pair
pp=collections.Counter()
for pr,labs in P['model110']: pp[len([l for l in labs if 'Model.Product.110' in l])]+=1
print('programs per pair histogram', sorted(pp.items())[:12], 'max', max(pp))
dp=[len([l for l in labs if 'Model.Product.110' in l]) for pr,labs in P['model110'] if pr in used]
print('drawn pairs: programs per pair mean', sum(dp)/len(dp))
only=[pr for pr,labs in P['model110'] if all('Model.Product.110' in l for l in labs)]
print('pairs only in Model.Product.110', len(only), 'drawn', len([x for x in only if x in used]))
print('---- passes of pairs')
names=['material','cubemap','zonly','depthshadow','xlu_zprepass','visualize','dyn0','dyn1','dyn2','dyn3','user0']
sm=SM['BNSH@0xf7d000']; name,mask,w,sh=sm['dyn'][2]
allc=collections.Counter(); drc=collections.Counter()
for pr,labs in P['model110']:
    ps=set()
    for l in labs:
        if '#BNSH@0xf7d000#' not in l: continue
        p=sm['var2prog'][int(l.split('#var')[1])]; ps.add(names[(sm['K'][p][w]&mask)>>sh])
    k='+'.join(sorted(ps)) if len(ps)<=2 else 'several'
    allc[k]+=1
    if pr in used: drc[k]+=1
for k,n in allc.most_common(14): print(f'{n:6d} {drc[k]:5d} {k}')
