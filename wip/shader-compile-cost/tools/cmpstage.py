"""cmpstage.py STAGE DIR_A DIR_B: per shader, compare the GPU program of one stage (vertex, fragment, compute, mesh,
object...) in the binary archives of two directories. Copy of cmpgpu.py with the stage section name as a parameter.
STAGE "list" prints the stage tags found in DIR_A's first archive."""
import re,os,struct,sys,collections
def sections(path):
    """Each 64-bit Mach-O in the file: its section bytes by "SEG,sect", and "@off", its file offset. The container's
    "__TEXT,__<stage>" sections hold the stage objects, so each object is labelled with the container section it lies in
    ("@in": vertex, fragment, compute, mesh, object); mesh and object programs are themselves labelled __compute."""
    a=open(path,"rb").read(); out=[]; ranges=[]
    for m in re.finditer(b"\xcf\xfa\xed\xfe",a):
        b=a[m.start():]; ncmds=struct.unpack_from("<I",b,16)[0]; off=32; secs={"@off":m.start()}
        for _ in range(ncmds):
            cmd,size=struct.unpack_from("<II",b,off)
            if cmd==0x19:
                n=struct.unpack_from("<I",b,off+64)[0]; so=off+72
                for i in range(n):
                    sect=b[so:so+16].rstrip(b"\0").decode(); seg=b[so+16:so+32].rstrip(b"\0").decode()
                    addr,sz,fo=struct.unpack_from("<QQI",b,so+32); secs[seg+","+sect]=b[fo:fo+sz]
                    if "__TEXT,__text" not in secs and seg=="__TEXT": ranges.append((m.start()+fo,m.start()+fo+sz,sect.strip("_")))
                    so+=80
            off+=size
        out.append(secs)
    for s in out:
        s["@in"]=next((nm for lo,hi,nm in ranges if lo<=s["@off"]<hi),None)
    return out
def obj(path,stage):
    hits=[s for s in sections(path) if "__TEXT,__text" in s and s["@in"]==stage]
    assert len(hits)<=1, (path,stage,len(hits))
    return hits[0] if hits else None
ST,A,B=sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>3 else None
names=sorted(os.listdir(A))
if ST=="list":
    for s in sections(A+"/"+names[0]): print(s["@off"],s["@in"],sorted(k for k in s if not k.startswith("@")))
    sys.exit()
both=same=missing=nostage=0; diff=[]; meta=collections.Counter()
for n in names:
    if not os.path.exists(B+"/"+n): missing+=1; continue
    a=obj(A+"/"+n,ST); b=obj(B+"/"+n,ST)
    if a is None or b is None: nostage+=1; continue
    both+=1
    if a["__TEXT,__text"]==b["__TEXT,__text"]: same+=1
    else: diff.append((n,len(a["__TEXT,__text"]),len(b["__TEXT,__text"])))
    for k in set(a)|set(b):
        if "STATS" in k or k=="__TEXT,__text" or k.startswith("@"): continue
        if a.get(k)!=b.get(k): meta[k]+=1
print("stage",ST,"archives in A:",len(names)," built both ways:",both," missing in B:",missing," no such stage object:",nostage)
print("GPU code byte-identical:",same," different:",len(diff))
print("other sections differing (shaders):",dict(meta))
for d in diff: print("  differs:",d)
