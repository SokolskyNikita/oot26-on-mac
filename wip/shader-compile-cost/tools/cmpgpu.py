"""cmpgpu.py DIR_A DIR_B: per shader, compare the fragment GPU program in the binary archives of two directories."""
import re,os,struct,sys,collections
def sections(path):
    a=open(path,"rb").read(); out=[]
    for m in re.finditer(b"\xcf\xfa\xed\xfe",a):
        b=a[m.start():]; ncmds=struct.unpack_from("<I",b,16)[0]; off=32; secs={}
        for _ in range(ncmds):
            cmd,size=struct.unpack_from("<II",b,off)
            if cmd==0x19:
                n=struct.unpack_from("<I",b,off+64)[0]; so=off+72
                for i in range(n):
                    sect=b[so:so+16].rstrip(b"\0").decode(); seg=b[so+16:so+32].rstrip(b"\0").decode()
                    addr,sz,fo=struct.unpack_from("<QQI",b,so+32); secs[seg+","+sect]=b[fo:fo+sz]; so+=80
            off+=size
        out.append(secs)
    return out
def frag(path):
    for s in sections(path):
        if "__TEXT,__text" in s and any(k.endswith(",__fragment") for k in s): return s
A,B=sys.argv[1],sys.argv[2]
names=sorted(os.listdir(A)); both=same=missing=0; diff=[]; meta=collections.Counter()
for n in names:
    if not os.path.exists(B+"/"+n): missing+=1; continue
    a=frag(A+"/"+n); b=frag(B+"/"+n)
    if a is None or b is None: continue
    both+=1
    if a["__TEXT,__text"]==b["__TEXT,__text"]: same+=1
    else: diff.append((n,len(a["__TEXT,__text"]),len(b["__TEXT,__text"])))
    for k in a:
        if "STATS" in k or k=="__TEXT,__text": continue
        if a[k]!=b.get(k): meta[k]+=1
print("built both ways:",both," missing in second:",missing)
print("GPU code byte-identical:",same," different:",len(diff))
print("other sections differing (shaders):",dict(meta))
for d in diff[:15]: print("  differs:",d)
