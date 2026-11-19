import sys, os, collections
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'extractor', 'shaders')); sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import lichii_cache as lc
from gdis import B
import struct
latest, counts = lc.load((sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin')))
NM = {0x020: 'FMUL', 0x021: 'FADD', 0x023: 'FFMA', 0x009: 'FMNMX'}
tot = collections.Counter(); ftz = collections.Counter(); rnd = collections.Counter(); b76 = collections.Counter()
progs = 0; progs_noftz = collections.Counter(); bystage = collections.Counter()
for (kind, key), p in latest.items():
    if kind != 1: continue
    pr = lc.program(p)
    if not pr['native']: continue
    progs += 1; st = str(lc.STAGES.get(pr["stage"], pr["stage"])); bystage[st] += 1
    n = pr['native']; miss = 0
    for i in range(0, len(n), 16):
        w = struct.unpack_from('<4I', n, i); base = w[0] & 0x1ff
        if base not in NM: continue
        nm = NM[base]; tot[(st, nm)] += 1
        f = B(w, 80, 1); ftz[(st, nm)] += f; miss += 1 - f
        if nm != 'FMNMX': rnd[(nm, B(w, 78, 2))] += 1; b76[(nm, B(w, 76, 1))] += 1
    if miss: progs_noftz[st] += 1
print('programs with native code:', progs, dict(bystage))
for k in sorted(tot): print(f'{k[0]:10} {k[1]:6} total {tot[k]:7}  FTZ bit set {ftz[k]:7}  ({100*ftz[k]/tot[k]:.2f}%)')
print('rounding field (bits 78-79):', dict(rnd)); print('bit 76:', dict(b76))
print('programs with at least one such instruction lacking FTZ:', dict(progs_noftz))
