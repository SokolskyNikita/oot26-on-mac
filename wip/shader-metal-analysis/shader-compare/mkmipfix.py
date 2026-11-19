"""mkmipfix.py MSL_0625 OUTDIR: write the three variants mipfix.swift compares, from the cached Metal shader whose
three texture samples sit behind a per-pixel condition (guest program 566f86aa1ac2ddb3; msl/0625.metal in an mtlb.py dump).
 v_asgen: as MoltenVK emits it.  v_ref: the samples hoisted out of the branch.  v_fix: gradients taken before the branch."""
import sys
t = open(sys.argv[1], errors='replace').read(); t = t[:t.rfind('\n}\n') + 3]; out = sys.argv[2]
VS = '''
struct VOut { float4 pos [[position]]; float4 in_attr0 [[user(locn0)]]; };
vertex VOut vmain(uint vid [[vertex_id]]) {
    float2 p = float2((vid << 1) & 2, vid & 2); VOut o; o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0);
    o.in_attr0 = float4(p.x * 1920.0 / 480.0, p.y * 1080.0 / 480.0, 0.0, 1.0); return o; }
'''
open(f'{out}/v_asgen.metal', 'w').write(t + VS)
uv = 'float2(_67, _73)'; names = ['fs_tex2_28', 'fs_tex2_30', 'fs_tex2_20']; anchor = '    float _77 = _76.x;\n'
ref = t; hoist = ''
for n in names:
    call = f'{n}.sample({n}Smplr, {uv})'; assert ref.count(call) == 1
    ref = ref.replace(call, f'_pre_{n}'); hoist += f'    float4 _pre_{n} = {call};\n'
assert anchor in ref
open(f'{out}/v_ref.metal', 'w').write(ref.replace(anchor, hoist + anchor) + VS)
fix = t
for n in names:
    call = f'{n}.sample({n}Smplr, {uv})'; fix = fix.replace(call, f'{n}.sample({n}Smplr, {uv}, gradient2d(_gdx, _gdy))')
open(f'{out}/v_fix.metal', 'w').write(fix.replace(anchor, f'    float2 _gdx = dfdx({uv}); float2 _gdy = dfdy({uv});\n' + anchor) + VS)
