import sys, struct, mmap, collections
f=open(sys.argv[1],'rb'); d=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
u8=lambda a:d[a]; u16=lambda a:struct.unpack_from('<H',d,a)[0]; i16=lambda a:struct.unpack_from('<h',d,a)[0]; u32=lambda a:struct.unpack_from('<I',d,a)[0]; u64=lambda a:struct.unpack_from('<Q',d,a)[0]
def s(a):
    n=u16(a); return d[a+2:a+2+n].decode('latin1')
for smi in range(u16(0x78)):
    r=0x80+0x100*smi
    no,nd,npg=u16(r+0xe4),u16(r+0xe6),u16(r+0xe8); sw,dw=u8(r+0xea),u8(r+0xeb)
    bnsh=u64(r+0xa8); g=bnsh+u16(bnsh+0x16); vt=bnsh+u64(g+0x20); nv=u32(g+0x1c)
    progs=u64(r+0x88); keys=u64(r+0x90)
    m=[]
    for p in range(npg):
        v=u64(progs+0x40*p+0x20); q,rem=divmod(v-vt,0x40); m.append(q if rem==0 and 0<=q<nv else None)
    print(s(u64(r)),'programs',npg,'mapped',sum(x is not None for x in m),'distinct targets',len(set(m)))
    W=sw+dw; K=[struct.unpack_from('<%dI'%W,d,keys+4*W*p) for p in range(npg)]
    st=collections.Counter(k[:sw] for k in K); print(' distinct static keys',len(st),'max programs per static key',max(st.values()), 'hist',sorted(collections.Counter(st.values()).items())[:12])
    print(' distinct full keys',len(set(K)))
    # choice names of options
    def opts(base,n):
        out=[]
        for i in range(n):
            q=base+0x28*i; ch=u64(q+8); nc=u16(q+0x18)
            # choices: try reading as dict-less array of string ptrs? print raw
            out.append((s(u64(q)),nc,i16(q+0x1a),u32(q+0x20),u8(q+0x24),u8(q+0x25),ch))
        return out
    O=opts(u64(r+8),no); D=opts(u64(r+0x18),nd)
    # how many static options actually vary across programs
    vary=0
    for (name,nc,df,mask,w,sh,ch) in O:
        vals=set((k[w]&mask)>>sh for k in K)
        if len(vals)>1: vary+=1
    print(' static options',no,'that vary across programs',vary)
    for (name,nc,df,mask,w,sh,ch) in D:
        vals=sorted(set((k[w]&mask)>>sh for k in K)); print('  dyn',name,'nchoice',nc,'values in table',vals[:12])
    if smi==0:
        print(' choices ptr raw for opt0', d[O[0][6]:O[0][6]+0x40].hex())
