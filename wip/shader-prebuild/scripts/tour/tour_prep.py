import struct, collections, pickle
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
P=REPO + '/wip/shader-prebuild/local/emulator-prebuild/eval/out-all/static.nx2prep'
f=open(P,'rb')
magic,ver,nenv,nrec,_=struct.unpack('<8sIIII',f.read(24))
print(magic,ver,nenv,nrec)
f.seek(24+16*nenv)
per=collections.Counter(); kinds=collections.Counter()
for i in range(nrec):
    kind,n,_=struct.unpack('<BBH',f.read(4)); f.read(4*n)
    klen=1056 if kind==0 else 24
    key=f.read(klen)
    if kind==0:
        hs=struct.unpack_from('<6Q',key,0)
        if hs[0]==0 and hs[2]==0 and hs[3]==0 and hs[4]==0 and hs[1] and hs[5]:
            per[('%016x'%hs[1],'%016x'%hs[5])]+=1; kinds['vp']+=1
        else: kinds['other-graphics']+=1
    else: kinds['compute']+=1
print(kinds); pickle.dump(per,open('prep_per_pair.pkl','wb'))
