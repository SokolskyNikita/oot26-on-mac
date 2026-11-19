"""mkvar2.py DIR: from DIR/v_asgen.metal and DIR/v_notex.metal write
 - coordinate variants v_<base>_<c>.metal (c = inc, pix, mag) that rewrite the interpolated UVs (attr5, attr6, attr13):
     inc: add a random offset per 2x2 quad (incoherent between quads, normal derivatives inside a quad -> mip 0 on 2048 textures)
     pix: random coordinates per pixel (incoherent, huge derivatives -> smallest mip if mipmapped, worst case without mips)
     mag: UVs scaled by 1/16 (smooth, heavily magnified -> best case cache reuse)
 - probe variants v_probe<k>.metal for each sample call k: output float4(coord.xy, texel footprint per pixel at 2048, 1) where the sample runs."""
import re, sys
d = sys.argv[1]
ANCHOR = '    main0_out out = {};\n'
HASH = '''    {{ uint2 _q = uint2(gl_FragCoord.xy){shift}; uint _h = (_q.x * 0x8da6b343u) ^ (_q.y * 0xd8163841u); _h ^= _h >> 15; _h *= 0x2c1b3c6du; _h ^= _h >> 12; _h *= 0x297a2d39u; _h ^= _h >> 15;
      float2 _o = float2(float(_h & 0xffffu), float(_h >> 16)) * (1.0 / 65536.0);
      {assign} }}
'''
def coord(src, kind):
    if kind == 'mag':
        ins = '    in.in_attr5.xy *= 0.0625; in.in_attr6.xy *= 0.0625; in.in_attr13.xy *= 0.0625;\n'
    else:
        assign = ('in.in_attr5.xy += _o; in.in_attr6.xy += _o.yx; in.in_attr13.xy += fract(_o * 1.618);' if kind == 'inc'
                  else 'in.in_attr5.xy = _o; in.in_attr6.xy = _o.yx; in.in_attr13.xy = fract(_o * 1.618);')
        ins = HASH.format(shift=' >> 1' if kind == 'inc' else '', assign=assign)
    assert ANCHOR in src
    return src.replace(ANCHOR, ANCHOR + ins, 1)
for base in ('asgen', 'notex'):
    s = open(f'{d}/v_{base}.metal').read()
    for k in ('inc', 'pix', 'mag'):
        open(f'{d}/v_{base}_{k}.metal', 'w').write(coord(s, k))
# probes
s = open(f'{d}/v_asgen.metal').read()
i = s.index('\nfragment '); head, body = s[:i], s[i:]
calls = []
for m in re.finditer(r'spvDescriptorSet0\.(fs_tex\w+)\.sample\(', body):
    j = m.end(); depth = 1; args = []; a0 = j
    while depth:
        c = body[j]
        if c == '(': depth += 1
        elif c == ')': depth -= 1
        elif c == ',' and depth == 1: args.append(body[a0:j]); a0 = j + 1
        j += 1
    args.append(body[a0:j - 1])
    calls.append((m.group(1), args[1].strip(), m.start(), j, len(args) > 2 and 'level(' in args[-1]))
info = []
for k, (tex, crd, st, en, lvl) in enumerate(calls):
    # statement end: next ';' at depth 0 after the call
    e = body.index(';\n', en) + 2
    line_start = body.rfind('\n', 0, st) + 1
    indent = re.match(r'[ \t]*', body[line_start:]).group(0)
    # coordinate expression may use names defined in the same statement only if inline; use the expression text as is
    probe = f'{indent}{{ float2 _pc = float2(({crd}).xy); _probe = float4(_pc, max(fwidth(_pc.x), fwidth(_pc.y)) * 2048.0, 1.0); }}\n'
    # for the inline sample inside a big expression the coord names are defined before the statement: insert before it
    b = body[:line_start] + probe + body[line_start:]
    b = b.replace(ANCHOR, ANCHOR + '    float4 _probe = float4(0.0);\n', 1)
    b = b.replace('    return out;', '    out.frag_color0 = _probe;\n    return out;')
    open(f'{d}/v_probe{k}.metal', 'w').write(head + b)
    info.append(f'probe{k} {tex} coord={crd[:90]} explicit_lod={lvl}')
open(f'{d}/probes.txt', 'w').write('\n'.join(info) + '\n')
print(len(calls), 'sample calls'); print('\n'.join(info))
