import struct,sys,glob,collections,json
def parse(b):
    # header: magic(4) ... offsets at 0x18: funclist off,size; pubmd off,size; privmd off,size; bitcode off,size
    fl_off,fl_sz,pm_off,pm_sz,pv_off,pv_sz,bc_off,bc_sz=struct.unpack_from('<8Q',b,0x18)
    n=struct.unpack_from('<I',b,fl_off)[0]
    o=fl_off+4; out=[]
    for _ in range(n):
        sz=struct.unpack_from('<I',b,o)[0]; e=o+sz; q=o+4; f={}
        while q<e:
            tag=b[q:q+4]; q+=4
            if tag==b'ENDT':break
            l=struct.unpack_from('<H',b,q)[0]; q+=2; d=b[q:q+l]; q+=l
            if tag==b'NAME': f['name']=d.rstrip(b'\0').decode()
            elif tag==b'TYPE': f['type']=d[0]
            elif tag==b'MDSZ': f['bcsize']=struct.unpack('<Q',d)[0]
            elif tag==b'OFFT': f['pub'],f['priv'],f['bc']=struct.unpack('<3Q',d)
            elif tag==b'HASH': f['hash']=d.hex()
        f['code']=(bc_off+f.get('bc',0), f.get('bcsize',0))
        out.append(f); o=e
    return out
if __name__=='__main__':
    idx=[];c=collections.Counter()
    for p in sorted(glob.glob('mtlb/*.metallib')):
        b=open(p,'rb').read()
        try: fs=parse(b)
        except Exception as ex: c['err']+=1; continue
        for f in fs:
            c[f.get('type')]+=1
            idx.append(dict(file=p,name=f.get('name'),type=f.get('type'),off=f['code'][0],size=f['code'][1]))
    json.dump(idx,open('mtlb_index.json','w'))
    print(c); print(collections.Counter(len(x['name']) for x in idx).most_common(5)); print(idx[:3])
    fr=sorted([x for x in idx if x['type']==1],key=lambda x:x['size'])
    print(len(fr),[x['size'] for x in fr[::max(1,len(fr)//15)]])
