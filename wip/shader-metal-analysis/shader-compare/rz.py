import sys, os, collections, struct
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'extractor', 'shaders')); sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import lichii_cache as lc
from gdis import B, decode, NAMES
latest, _ = lc.load((sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin')))
st_cnt = collections.Counter(); progs = collections.Counter(); nxt = collections.Counter(); scale = collections.Counter(); form = collections.Counter(); ex = []
for (kind, key), p in latest.items():
    if kind != 1: continue
    pr = lc.program(p); n = pr['native']
    if not n: continue
    st = str(lc.STAGES.get(pr['stage'], pr['stage'])); D = decode(n); hit = 0
    for d in D:
        w = d['w']; base = d['op'] & 0x1ff
        if base in (0x20, 0x21, 0x23) and B(w, 78, 2):
            hit += 1; st_cnt[(st, NAMES[base], B(w, 78, 2))] += 1
            if base == 0x20: scale[B(w, 84, 3)] += 1; form[d['src']] += 1
            # first later instruction that reads the destination
            for e in D[d['i'] + 1: d['i'] + 40]:
                if d['dst'] in (e['a'], e['b'], e['c']):
                    nxt[(NAMES[base], e['name'])] += 1; break
            else: nxt[(NAMES[base], '(none within 40)')] += 1
            if len(ex) < 6 and base == 0x20: ex.append((f'{key:016x}', st, d['i'], d['src'], '%08x %08x %08x %08x' % w))
    if hit: progs[st] += 1
print('by stage/op/rounding:', dict(st_cnt)); print('programs:', dict(progs)); print('FMUL scale field:', dict(scale), 'operand form:', dict(form))
print('first consumer:', nxt.most_common(15)); print(*ex, sep='\n')
