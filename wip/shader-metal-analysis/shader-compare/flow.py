"""Which implicit-LOD texture samples run under a condition that can differ between the pixels of a 2x2 quad?
Backward data flow over each cached Ampere fragment program. Classes: U quad-uniform, V per-pixel, ? unknown."""
import sys, os, collections, struct, functools
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..', 'extractor', 'shaders')); sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import lichii_cache as lc
sys.setrecursionlimit(100000)
def B(w, o, c): return ((w[0] | w[1] << 32 | w[2] << 64 | w[3] << 96) >> o) & ((1 << c) - 1)
TEXB = {0x160, 0x161, 0x163, 0x164, 0x166, 0x167, 0x169, 0x16a, 0x16c, 0x16f, 0x170}
ALU2 = {0x02: 'MOV', 0x07: 'SEL', 0x08: 'FSEL', 0x09: 'FMNMX', 0x0a: 'FSET', 0x20: 'FMUL', 0x21: 'FADD'}
ALU3 = {0x10: 'IADD3', 0x11: 'LEA', 0x12: 'LOP3', 0x19: 'SHF', 0x23: 'FFMA'}
UNARY = {0x104, 0x105, 0x106, 0x107, 0x108, 0x109}
SETP = {0x0b, 0x0c}
def analyse(native, ipa_const_uniform=True):
    N = len(native) // 16
    W = [struct.unpack_from('<4I', native, i * 16) for i in range(N)]
    op = [w[0] & 0xfff for w in W]; base = [o & 0x1ff for o in op]; form = [o >> 9 for o in op]
    for i in range(N):
        if op[i] in (0xab9, 0xabb): base[i] = 0x0b9
    xp = [B(w, 12, 4) for w in W]   # execution predicate, 7 = always
    bra = [i for i in range(N) if op[i] == 0x947]
    def rdst(i):   # registers written
        b, w = base[i], W[i]; d = B(w, 16, 8)
        if b in SETP or b in (0x1c, 0x147, 0x145, 0x141, 0x14d, 0x11a, 0x15b): return ()
        if b in TEXB:
            s = B(w, 64, 8); r = [d, d + 1]
            if s != 255: r += [s, s + 1]
            return tuple(x for x in r if x < 255)
        if b in (0x181, 0x184): return tuple(x for x in (d, d + 1, d + 2, d + 3) if x < 255)
        return (d,) if d != 255 else ()
    def pdst(i):
        b, w = base[i], W[i]
        if b in SETP or b == 0x1c: return tuple(p for p in (B(w, 81, 3), B(w, 84, 3)) if p != 7)
        if op[i] in (0x806, 0x886, 0x804, 0x3a1, 0x234, 0x434, 0x634, 0x233, 0x433, 0x633): return tuple(range(7))   # other predicate writers: unknown which
        return ()
    rw = collections.defaultdict(list); pw = collections.defaultdict(list)
    for i in range(N):
        for r in rdst(i): rw[r].append(i)
        for p in pdst(i): pw[p].append(i)
    def defs(table, key, at):
        out = []
        for i in reversed(table.get(key, ())):
            if i >= at: continue
            out.append(i)
            if xp[i] == 7 and not any(j < at for j in bra): break   # an unpredicated write kills, unless a branch may skip it
        return out
    def join(xs):
        xs = set(xs)
        return 'V' if 'V' in xs else '?' if '?' in xs else 'U'
    @functools.lru_cache(None)
    def reg(r, at):
        if r == 255: return 'U'
        ds = defs(rw, r, at)
        return join(val(i) for i in ds) if ds else '?'
    @functools.lru_cache(None)
    def pred(p, at):
        p &= 7
        if p == 7: return 'U'
        ds = defs(pw, p, at)
        return join(val(i) for i in ds) if ds else '?'
    @functools.lru_cache(None)
    def val(i):
        b, w, f = base[i], W[i], form[i]; a = B(w, 24, 8); bb = B(w, 32, 8); c = B(w, 64, 8); src = []
        if xp[i] != 7:   # predicated: keeps the old value where the predicate is false
            src.append(pred(xp[i], i))
            for r in rdst(i)[:1]: src.append(reg(r, i))
            for p in pdst(i)[:1]: src.append(pred(p, i))
        if b == 0x126: src.append('U' if (B(w, 78, 1) and ipa_const_uniform) else 'V')                 # IPA; constant mode is per primitive
        elif b in TEXB: src += [reg(x, i) for x in (a, a + 1, bb, bb + 1) if x < 255]
        elif b in (0x181, 0x184): src += [reg(a, i), reg(min(a + 1, 255), i)]
        elif b == 0x182: src.append(reg(a, i))
        elif b == 0x0b9: pass                                                   # ULDC: uniform
        elif op[i] in (0xc02,) or (b == 0x02 and f in (4, 5)): pass             # MOV from uniform register / immediate / cbuf
        elif b == 0x02: src.append(reg(bb, i))
        elif b in ALU2 or b in SETP:
            src.append(reg(a, i))
            if f == 1: src.append(reg(bb, i))
            if b in (0x07, 0x08) or b in SETP:
                q = B(w, 87, 4)
                if q & 7 != 7: src.append(pred(q, i))
        elif b in ALU3:
            src.append(reg(a, i))
            if f == 1: src += [reg(bb, i), reg(c, i)]
            else: src.append(reg(c, i))
        elif b in UNARY: src.append(reg(bb, i) if f == 1 else 'U')
        elif b == 0x1c:                                                         # PLOP3
            for o in (87, 77, 68):
                q = B(w, o, 4)
                if q & 7 != 7 and not (o == 68 and B(w, 67, 1)): src.append(pred(q, i))
        elif b == 0x05: pass                                                    # CS2R
        else: src.append('?')
        return join(src)
    out = []
    for i in range(N):
        if base[i] not in (0x160, 0x161): continue
        lod = B(W[i], 87, 3)
        if lod not in (0, 2, 6): continue
        # conditional execution: own predicate, or lying inside a forward branch's skipped range
        conds = []
        if xp[i] != 7: conds.append(('pred', pred(xp[i], i)))
        for j in bra:
            if j >= i: continue
            raw = (W[j][1] & ~3) | ((W[j][2] & 0x3ffff) << 32); rel = raw - (1 << 50) if raw >> 49 else raw
            tgt = j + 1 + rel // 16
            if tgt > i and (xp[j] != 7 or B(W[j], 87, 4) != 7):
                conds.append(('branch', join([pred(xp[j], j), pred(B(W[j], 87, 4), j)])))
        out.append((i, conds))
    r2ur = [(i, reg(B(W[i], 24, 8), i), pred(xp[i], i) if xp[i] != 7 else None) for i in range(N) if op[i] == 0x3c2]
    return out, N, r2ur
