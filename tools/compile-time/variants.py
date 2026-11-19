# variants.py: write the MSL variants the Metal compile-time checks use, into out/.
import re, random
src = open('out/F.metal').read()
opt = open('out/f_opt.metal').read()
opt = re.sub(r'main_z\d+', 'main0', opt)

def nopragma(s): return re.sub(r'^\s*#pragma metal fp.*\n', '', s, flags=re.M)
def plain(s):
    s = s.replace('return fma(l, r, T(-0.0));', 'return l * r;').replace('return fma(T(1), l, r);', 'return l + r;')
    return s
def macro(s):
    # drop the two scalar helper templates and use macros instead
    s = re.sub(r'template<typename T>\nT spvFMul\(T l, T r\)\n\{.*?\n\}\n', '#define spvFMul(l, r) ((l) * (r))\n', s, flags=re.S)
    s = re.sub(r'template<typename T>\nT spvFAdd\(T l, T r\)\n\{.*?\n\}\n', '#define spvFAdd(l, r) ((l) + (r))\n', s, flags=re.S)
    return s
def noprecise(s): return s.replace('precise::', '')
SEL = re.compile(r'^([ \t]*)if \((.*)\)\n\1\{\n[ \t]*(_\d+) = (.*);\n\1\}\n\1else\n\1\{\n[ \t]*\3 = (.*);\n\1\}', re.M)
def select(s):
    n = 1
    total = 0
    while n:
        s, n = SEL.subn(r'\1\3 = (\2) ? (\4) : (\5);', s)
        total += n
    select.count = total
    return s
def scaled(s, k):
    m = re.search(r'^fragment main0_out main0\((.*)\)\n', s, re.M)
    sig = m.group(1)
    plain_sig = re.sub(r'\s*\[\[[^\]]*\]\]', '', sig)
    names = [p.strip().split()[-1].lstrip('&') for p in plain_sig.split(',')]
    head, body = s[:m.start()], s[m.end():]
    out = head
    for i in range(k):
        out += f'static inline __attribute__((always_inline)) main0_out body{i}({plain_sig})\n' + body + '\n'
    out += f'fragment main0_out main0({sig})\n{{\n    main0_out o = body0({", ".join(names)});\n'
    for i in range(1, k):
        out += f'    in.in_attr2 += float4({i}.5); in.in_attr3 *= float4({i}.25);\n    o.frag_color0 += body{i}({", ".join(names)}).frag_color0;\n'
    return out + '    return o;\n}\n'

W = lambda n, s: open(f'out/{n}.metal', 'w').write(s)
W('F_nopragma', nopragma(src))
W('F_plain', plain(nopragma(src)))
W('F_macro', macro(src))
W('F_noprecise', noprecise(src))
W('F_select', select(src)); print('selects flattened:', select.count)
W('F_all', select(noprecise(macro(src))))
W('F_opt', opt)
W('F_opt_all', select(noprecise(macro(opt)))); print('selects flattened (opt):', select.count)
for k in (1, 2, 4): W(f'F_x{k}', scaled(src, k))
W('T_trivial', 'fragment float4 main0() { return float4(1.0); }\n')
W('T_stdlib', '#include <metal_stdlib>\n#include <simd/simd.h>\nusing namespace metal;\nfragment float4 main0() { return float4(1.0); }\n')

# A "natural style" stand-in for the same workload: same interface (5 float4 varyings, 13 samples, one
# float4 output), vector maths written the way a person or a GLSL compiler would, about one vector statement
# per three guest scalar instructions (the guest program has ~1,700 instructions -> ~560 statements).
random.seed(7)
L = ['#include <metal_stdlib>', 'using namespace metal;',
     'struct U { float4 data[128]; };',
     'struct main0_out { float4 frag_color0 [[color(0)]]; };',
     'struct main0_in { float4 in_attr2 [[user(locn2)]]; float4 in_attr3 [[user(locn3)]]; float4 in_attr4 [[user(locn4)]]; float4 in_attr5 [[user(locn5)]]; float4 in_attr6 [[user(locn6)]]; };']
texs = ', '.join(f'texture2d<float> t{i} [[texture({i})]]' for i in range(13))
L.append(f'fragment main0_out main0(main0_in in [[stage_in]], constant U& u [[buffer(0)]], {texs}, sampler s [[sampler(0)]], float4 gl_FragCoord [[position]])')
L.append('{')
vals = ['in.in_attr2', 'in.in_attr3', 'in.in_attr4', 'in.in_attr5', 'in.in_attr6', 'gl_FragCoord']
n = 0
def v(): return random.choice(vals[-12:] if random.random() < .7 else vals)
def new(expr):
    global n
    L.append(f'    float4 v{n} = {expr};'); vals.append(f'v{n}'); n += 1
tex_at = set(random.sample(range(20, 520), 13)); ti = 0
depth = 0
for i in range(560):
    if i in tex_at:
        new(f't{ti}.sample(s, {v()}.xy * u.data[{random.randrange(128)}].xy + {v()}.zw)'); ti += 1; continue
    r = random.random()
    c = f'u.data[{random.randrange(128)}]'
    if r < .30: new(f'{v()} * {v()} + {c}')
    elif r < .45: new(f'mix({v()}, {v()}, saturate({v()}))')
    elif r < .55: new(f'float4(normalize({v()}.xyz), dot({v()}.xyz, {v()}.xyz))')
    elif r < .65: new(f'max({v()}, {c}) - min({v()}, {v()})')
    elif r < .72: new(f'pow(abs({v()}), {c}) * {v()}.w')
    elif r < .80: new(f'{v()}.zxyw * rsqrt(max(dot({v()}, {v()}), 1e-6))')
    elif r < .88: new(f'select({v()}, {v()}, {v()} > {c})')
    elif r < .94: new(f'float4(cross({v()}.xyz, {v()}.xyz), {v()}.x) * {c}')
    else:
        a, b = v(), v()
        L.append(f'    float4 v{n};'); L.append(f'    if ({a}.x > {c}.y) {{ v{n} = {a} * {b}; }} else {{ v{n} = {b} - {a} * {c}; }}'); vals.append(f'v{n}'); n += 1
L.append('    main0_out out; out.frag_color0 = ' + ' + '.join(vals[-40:]) + ';')
L.append('    return out;'); L.append('}')
W('R_natural', '\n'.join(L) + '\n')
