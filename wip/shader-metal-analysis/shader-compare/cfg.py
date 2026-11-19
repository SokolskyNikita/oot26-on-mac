"""CFG inventory of one function in an LLVM .ll file: every conditional branch, its shape and what it guards."""
import re,sys,collections
def parse(path):
    s=open(path).read(); body=s[s.index('define '):]; body=body[:body.index('\n}\n')]
    blocks=collections.OrderedDict(); cur='entry'; blocks[cur]=[]
    for line in body.split('\n')[1:]:
        m=re.match(r'^([\w.]+):',line)
        if m: cur=m.group(1); blocks[cur]=[]; continue
        line=line.strip()
        if line and not line.startswith(';'): blocks[cur].append(line)
    return blocks
def kind(l):
    if ' call ' in ' '+l:
        t=re.search(r'@([\w.]+)\(',l).group(1)
        return 'sample' if 'sample_texture' in t else t.replace('air.','').split('.')[0]
    m=re.match(r'(?:%[\w.]+ = )?(\w+)',l); return m.group(1)
FREE={'bitcast','getelementptr','extractelement','insertelement','extractvalue','insertvalue','phi','br','zext','trunc','shufflevector'}
if __name__=='__main__':
    B=parse(sys.argv[1]); names=list(B)
    succ={}
    for n,ins in B.items():
        t=ins[-1]; succ[n]=re.findall(r'label %([\w.]+)',t)
    pred=collections.defaultdict(list)
    for n,ss in succ.items():
        for x in ss: pred[x].append(n)
    order={n:i for i,n in enumerate(names)}
    back=[(n,x) for n,ss in succ.items() for x in ss if order[x]<=order[n]]
    defs={}
    for n,ins in B.items():
        for l in ins:
            m=re.match(r'(%[\w.]+) = (.*)',l)
            if m: defs[m.group(1)]=(n,m.group(2))
    conds=[n for n in names if B[n][-1].startswith('br i1')]
    print('blocks',len(B),'cond branches',len(conds),'back edges (loops)',len(back))
    shapes=collections.Counter(); guarded=collections.Counter(); condsrc=collections.Counter(); sizes=[]; rows=[]
    for n in conds:
        c=re.match(r'br i1 (\S+),',B[n][-1]).group(1); a,b=succ[n]
        def side(x,other):
            # blocks reached from x before the join with the other arm (single-block arms only)
            return x if len(pred[x])==1 else None
        sa,sb=side(a,b),side(b,a)
        arms=[x for x in (sa,sb) if x]
        if len(arms)==2 and succ[sa]==succ[sb] and len(succ[sa])==1: shape='diamond (if/else)'
        elif len(arms)==1 and len(succ[arms[0]])==1 and succ[arms[0]][0] in (a,b): shape='triangle (if)'
        elif len(arms)==2 and (succ[sa]==[b] or succ[sb]==[a]): shape='triangle (if)'; arms=[sa if succ[sa]==[b] else sb]
        else: shape='larger region'
        shapes[shape]+=1
        cd=defs.get(c,(None,c))[1]
        ck='icmp' if cd.startswith('icmp') else 'fcmp' if cd.startswith('fcmp') else 'simd_any' if 'simd_any' in cd else cd.split()[0]
        condsrc[ck]+=1
        cont=collections.Counter()
        if shape!='larger region':
            for x in arms:
                for l in B[x]: cont[kind(l)]+=1
            real=sum(v for k,v in cont.items() if k not in FREE)
            sizes.append(real); 
            for k,v in cont.items():
                if k not in FREE: guarded[k]+=v
        rows.append((n,shape,ck,dict((k,v) for k,v in cont.items() if k not in FREE)))
    print('shapes',dict(shapes)); print('condition comes from',dict(condsrc))
    print('non-free ops inside simple arms, total',dict(guarded))
    print('real ops per simple branch: histogram',sorted(collections.Counter(sizes).items()))
    emptyish=sum(1 for r in rows if r[1]!='larger region' and not r[3]); print('branches guarding nothing but phi/bitcast (pure select):',emptyish)
    loadonly=sum(1 for r in rows if r[1]!='larger region' and set(r[3])=={'load'}); print('branches guarding only loads:',loadonly)
    for r in rows:
        if r[1]=='larger region' or 'sample' in r[3] or sum(r[3].values())>6: print('  ',r)
    # phis per merge
    ph=collections.Counter(sum(1 for l in ins if ' = phi ' in l) for ins in B.values()); print('phis per block',sorted(ph.items()))
