import sys,os,struct,re,collections,glob,pickle
sys.path.insert(0,__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'extractor', 'shaders'))
import lichii_cache as lc
def bits(w,o,c):
    v=w[0]|w[1]<<32|w[2]<<64|w[3]<<96
    return (v>>o)&((1<<c)-1)
def guest_sig(native):
    ipa=set(); tex=collections.Counter(); ops=collections.Counter()
    for i in range(0,len(native),16):
        w=struct.unpack_from('<4I',native,i); op=w[0]&0xfff; ops[op]+=1
        if op in(0x326,0x526): ipa.add(bits(w,64,8))
        if op in(0xb60,0xb66,0xb63,0xb6c,0xb69,0xb6f): tex[bits(w,40,14)]+=1
    return frozenset(ipa),tex,ops
def msl_sig(s):
    m=re.search(r'^fragment .*$',s,re.M); body=s[m.start():]
    ipa=set()
    for n,c in re.findall(r'in\.in_attr(\d+)\.([xyzw])',body): ipa.add(0x20+4*int(n)+'xyzw'.index(c))
    tex=collections.Counter(re.findall(r'spvDescriptorSet0\.(fs_tex\w+?)\.(?:sample|read|gather)',body))
    return frozenset(ipa),tex,body.count('\n')
if __name__=='__main__':
    latest,_=lc.load(os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin'))
    G={}
    for (k,key),v in latest.items():
        if k==1:
            p=lc.program(v)
            if p['stage']==4: G[p['unique_hash']]=(guest_sig(p['native']),p)
    M={}
    for f in sorted(glob.glob('msl/*.metal')):
        s=open(f,errors='replace').read()
        if re.search(r'^fragment ',s,re.M): M[f]=msl_sig(s)
    pickle.dump((G,M),open('sigs.pkl','wb'))
    # example
    f='msl/0542.metal'; print(sorted(M[f][0]), M[f][1], M[f][2])
    cand=[(h,g) for h,(g,p) in G.items() if g[0]==M[f][0]]
    print(len(cand))
    for h,g in cand[:6]: print(f'{h:016x}',{hex(k):v for k,v in g[1].items()}, sum(g[2].values()))
