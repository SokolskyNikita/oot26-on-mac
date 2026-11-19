"""mkvar.py DIR: write variants of DIR/fs.metal (prepared by fsprep.py) to test one translation artefact at a time."""
import re,sys
d=sys.argv[1]; src=open(d+'/fs.metal').read()
i=src.index('\nfragment '); head,body=src[:i],src[i:]
def plain(h,b): return h.replace('return fma(l, r, T(-0.0));','return l * r;').replace('return fma(T(1), l, r);','return l + r;'),b
def noprecise(h,b): return h,b.replace('precise::','')
def nosimd(h,b):
    h+='\ntemplate<typename T> inline T spvNoShuffle(T v, uint) { return v; }\n'
    b=b.replace('spvSubgroupShuffle(','spvNoShuffle(').replace('spvSubgroupBallot(true)','uint4(1u, 0u, 0u, 0u)').replace('simd_any(true)','true')
    return h,b
SEL=re.compile(r'^([ \t]*)if \((.*)\)\n\1\{\n[ \t]*(_\d+) = (.*);\n\1\}\n\1else\n\1\{\n[ \t]*\3 = (.*);\n\1\}',re.M)
def select(h,b):
    tot=0;n=1
    while n:
        b,n=SEL.subn(r'\1\3 = (\2) ? (\4) : (\5);',b); tot+=n
    select.n=tot; return h,b
def norint(h,b): return h,b.replace('uint(rint(','uint((')
def probe(h,b):
    if '_1333' not in b: return h,b
    return h,b.replace('    return out;','    out.frag_color0 = float4(float(_1333), float(_1327), float(_1339), float(_654));\n    return out;')
def nofneg(h,b):  # sign flip through integer xor -> float negate
    out=[];pos=0;n=0;key='as_type<float>('
    while True:
        i=b.find(key,pos)
        if i<0: out.append(b[pos:]); break
        j=i+len(key);depth=1
        while depth: depth+={'(':1,')':-1}.get(b[j],0); j+=1
        inner=b[i+len(key):j-1]
        if inner.endswith(' ^ 2147483648u') and inner.count('(')==inner.count(')'):
            x=inner[:-len(' ^ 2147483648u')]
            # only when the xor is the top-level operator
            d=0;top=True
            for ch in x:
                d+={'(':1,')':-1}.get(ch,0)
                if d==0 and ch in ' ' : top=False
            if top or (x.startswith('(') or x.startswith('as_type') or x.startswith('_')) and not any(c==' ' and dd==0 for c,dd in zip(x,__import__('itertools').accumulate(({'(':1,')':-1}.get(ch,0) for ch in x)))):
                out.append(b[pos:i]+'(-as_type<float>('+x+'))'); pos=j; n+=1; continue
        out.append(b[pos:i+len(key)]); pos=i+len(key)
    nofneg.n=n; return h,''.join(out)
def notex(h,b):
    out=[];pos=0;n=0
    import re as _re
    for mm in _re.finditer(r'spvDescriptorSet0\.fs_tex\w+\.sample\(',b):
        if mm.start()<pos: continue
        j=mm.end();depth=1
        while depth: depth+={'(':1,')':-1}.get(b[j],0); j+=1
        out.append(b[pos:mm.start()]+'float4(0.5)'); pos=j; n+=1
    out.append(b[pos:]); notex.n=n; return h,''.join(out)
V={'asgen':[], 'notex':[notex], 'plain':[plain], 'noprecise':[noprecise], 'nosimd':[nosimd], 'select':[select], 'norint':[norint], 'nofneg':[nofneg],
   'all':[plain,noprecise,nosimd,select,norint,nofneg], 'probe':[probe]}
for name,fs in V.items():
    h,b=head,body
    for f in fs: h,b=f(h,b)
    open(f'{d}/v_{name}.metal','w').write(h+b)
print('selects flattened',select.n,'of',body.count('if ('),'ifs; sign flips rewritten',nofneg.n,'; simd calls',body.count('spvSubgroupShuffle('),body.count('spvSubgroupBallot('),body.count('simd_any('))
