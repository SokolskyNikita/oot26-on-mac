import sys, struct, mmap
f=open(sys.argv[1],'rb'); d=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
u8=lambda a:d[a]; u16=lambda a:struct.unpack_from('<H',d,a)[0]; u32=lambda a:struct.unpack_from('<I',d,a)[0]; u64=lambda a:struct.unpack_from('<Q',d,a)[0]
def s(a):
    n=u16(a); return d[a+2:a+2+n].decode('latin1')
print('magic',d[:8],'ver',d[8:12].hex(),'size',u32(0x1c),hex(u32(0x18)),'name',s(u32(0x10)-2) if u32(0x10) else None)
sm=u64(0x48); n=u16(0x78); print('sm table',hex(sm),'count@0x7a',n, 'u16@0x78',u16(0x78))
tot=0
for i in range(n):
    r=sm+0x100*i
    no,nd,npg=u16(r+0xe4),u16(r+0xe6),u16(r+0xe8); sw,dw=u8(r+0xea),u8(r+0xeb)
    bnsh=u64(r+0xa8); nvar=u32(bnsh+u16(bnsh+0x16)+0x1c) if d[bnsh:bnsh+4]==b'BNSH' else None
    tot+=npg
    print(i,s(u64(r)),'static',no,'dyn',nd,'progs',npg,'words',sw,dw,'bnsh',hex(bnsh),'bnsh_vars',nvar, 'hdr', d[r+0xe0:r+0x100].hex())
print('total programs',tot)
