import sys,os,struct,re,collections
sys.path.insert(0,__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'extractor', 'shaders'))
import lichii_cache as lc
def llconsts(path):
    s=open(path).read(); out=collections.Counter()
    for m in re.finditer(r'float (0x[0-9A-Fa-f]{16}|-?\d+\.\d+e[+-]\d+)',s):
        t=m.group(1)
        v=struct.unpack('>d',bytes.fromhex(t[2:]))[0] if t.startswith('0x') else float(t)
        try: out[struct.unpack('<I',struct.pack('<f',v))[0]]+=1
        except OverflowError: pass
    return out
TRIV={0,0x3f800000,0x80000000,0xbf800000,0x3f000000,0x40000000}
def guest_imms(native):
    out=collections.Counter()
    for i in range(0,len(native),16):
        w=struct.unpack_from('<4I',native,i); op=w[0]&0xfff
        if op>>8 in (4,8) or op>>8==6: out[w[1]]+=1
    return out
if __name__=='__main__':
    latest,_=lc.load(os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin'))
    progs=[lc.program(v) for (k,key),v in latest.items() if k==1]
    A=set(llconsts(sys.argv[1]))-TRIV
    print('air consts',len(A))
    res=[]
    for p in progs:
        if p['stage']!=4: continue
        G=set(guest_imms(p['native']))
        hit=len(A&G)
        res.append((hit, p['n_native'], f"{p['unique_hash']:016x}"))
    res.sort(reverse=True)
    print(res[:8])
