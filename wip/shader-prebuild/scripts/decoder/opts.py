import sys, struct, mmap, collections
f=open(sys.argv[1],'rb'); d=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
u8=lambda a:d[a]; u16=lambda a:struct.unpack_from('<H',d,a)[0]; i16=lambda a:struct.unpack_from('<h',d,a)[0]; u32=lambda a:struct.unpack_from('<I',d,a)[0]; u64=lambda a:struct.unpack_from('<Q',d,a)[0]
def s(a):
    n=u16(a); return d[a+2:a+2+n].decode('latin1')
smi=int(sys.argv[2]); r=0x80+0x100*smi
print('SM',s(u64(r))); print('record'); 
for o in range(0,0x100,8): print(hex(o), d[r+o:r+o+8].hex(), hex(u64(r+o)))
no,nd,npg=u16(r+0xe4),u16(r+0xe6),u16(r+0xe8); sw,dw=u8(r+0xea),u8(r+0xeb)
# program->variation identity
bnsh=u64(r+0xa8); g=bnsh+u16(bnsh+0x16); vt=bnsh+u64(g+0x20)
progs=u64(r+0x88); bad=0
for p in range(npg):
    v=u64(progs+0x40*p+0x20)
    if v!=vt+0x40*p: bad+=1
print('program p -> BNSH variation p mismatches:',bad,'of',npg, 'vt',hex(vt), 'first prog var', hex(u64(progs+0x20)))
print('program record 0:', d[progs:progs+0x40].hex())
def dumpopts(base,n,label):
    print(label,'records at',hex(base))
    for i in range(n):
        q=base+0x28*i
        name=s(u64(q)); 
        print(' ',i,name,'raw',d[q+8:q+0x28].hex(),'nchoice',u16(q+0x18),'def',i16(q+0x1a),'mask',hex(u32(q+0x20)),'word',u8(q+0x24),'shift',u8(q+0x25))
        if i>=int(sys.argv[3]): break
dumpopts(u64(r+0x08),no,'static')
dumpopts(u64(r+0x18),nd,'dynamic')
