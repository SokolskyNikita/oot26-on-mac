"""Rough listing of an Ampere (SM86) fragment program from Lichii's cache: mnemonic, operand form, predicate, modifiers."""
import struct,sys,collections
NAMES={0x002:'MOV',0x007:'SEL',0x008:'FSEL',0x009:'FMNMX',0x00a:'FSET',0x00b:'FSETP',0x00c:'ISETP',0x010:'IADD3',0x011:'LEA',
0x012:'LOP3',0x019:'SHF',0x020:'FMUL',0x021:'FADD',0x023:'FFMA',0x105:'F2I',0x108:'MUFU',0x126:'IPA',0x160:'TEX',
0x181:'LDG',0x182:'LDC',0x0b9:'ULDC',0x1c2:'R2UR',0x082:'UMOV',0x099:'USHF',0x11a:'DEPBAR',0x005:'CS2R',0x145:'BSSY',0x141:'BSYNC',
0x147:'BRA',0x14d:'EXIT'}
FORM={1:'reg',2:'imm',3:'reg/imm',4:'imm',5:'cbuf',6:'ureg',7:'ureg'}
MUFU={0:'COS',1:'SIN',2:'EX2',3:'LG2',4:'RCP',5:'RSQ',8:'SQRT'}
def B(w,o,c):
    v=w[0]|w[1]<<32|w[2]<<64|w[3]<<96
    return (v>>o)&((1<<c)-1)
def decode(b):
    out=[]
    for i in range(0,len(b),16):
        w=struct.unpack_from('<4I',b,i); op=w[0]&0xfff; base=op&0x1ff
        if op==0xab9: base=0x0b9
        n=NAMES.get(base,f'op{op:03x}'); form=op>>9
        p=B(w,12,4); pred=None if p==7 else ('!' if p&8 else '')+f'P{p&7}'
        d=dict(i=i//16,op=op,name=n,pred=pred,dst=B(w,16,8),a=B(w,24,8),b=B(w,32,8),c=B(w,64,8),w=w,
               src='cbuf' if op>>8 in(0xa,0xb) and base not in(0x160,0x182,0x0b9) else 'imm' if op>>8 in(4,8) and base in(0x2,0x9,0x20,0x21,0x23,0x7,0xc,0x10,0x12) else 'ureg' if op>>8 in(0xc,0xe) else 'reg')
        if base in(0x20,0x21,0x23): d['sat']=B(w,77,1)
        if base==0x108: d['sub']=MUFU.get(B(w,74,6),'?')
        if base==0x160: d['bindless']=op==0xf60; d['dim']=B(w,61,3); d['lodmode']=B(w,87,3); d['mask']=B(w,72,4)
        if base in(0xb,0xc): d['pd']=B(w,81,3)
        out.append(d)
    return out
if __name__=='__main__':
    D=decode(open(sys.argv[1],'rb').read())
    for d in D:
        extra=' '.join(f'{k}={d[k]}' for k in('sat','sub','bindless','dim','lodmode','pd') if d.get(k))
        print(f"{d['i']:4d} {d['pred'] or '':4s} {d['name']:7s} {d['src']:5s} R{d['dst']:<3d} a=R{d['a']:<3d} b={d['b']:<3d} c=R{d['c']:<3d} {extra}  {'%08x %08x %08x %08x'%d['w']}")
