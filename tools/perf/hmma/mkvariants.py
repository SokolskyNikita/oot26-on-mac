#!/usr/bin/env python3
"""mkvariants.py DUMP.metal OUTDIR: write variants of the network-upscale kernel whose emulated HMMA (_97) moves the
warp's fragments through threadgroup memory instead of simd_shuffle. Also writes unit.metal, a kernel that runs the
original _97 and each replacement on the same inputs so the CPU can compare the results bit for bit."""
import re, sys, os
src = open(sys.argv[1]).read(); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
a = src.index("static inline __attribute__((always_inline))\nuint2 _97(")
b = src.index("\n}\n", a) + 3
orig_fn = src[a:b]
ROUND = orig_fn[orig_fn.index("            uint _316"):orig_fn.index("            _102 = _136 + 1u;")]

def body(layout="s6", tail=True, barrier="simd", rnd="manual"):
    """The replacement helper. Each lane stores its 4 A words and 2 B words in threadgroup memory, then reads the
    lanes of its A row block (4 lanes) and B column block (8 lanes). Same FMA order and rounding as the original.
    layout s6: 6 scalar words a lane. v: one uint4 (A) and one uint2 (B) a lane, read as vectors.
    rnd native: the fp16 rounding of the accumulators is a float -> half -> float conversion."""
    B = ("simdgroup_barrier" if barrier == "simd" else "threadgroup_barrier") + "(mem_flags::mem_threadgroup)"
    rounding = ROUND if rnd == "manual" else "".join(f"            _{n} = float(half(_{n}));\n" for n in (104, 105, 106, 107))
    def grp(g):
        s = ""
        for comp in range(4):
            if layout == "s6":
                b0 = f"W[(bb + {comp}u) * 6u + {4 + g}u]"; b1 = f"W[(bb + {comp + 4}u) * 6u + {4 + g}u]"
                a0 = f"W[(ab + {comp}u) * 6u + {2 * g}u]"; a1 = f"W[(ab + {comp}u) * 6u + {2 * g + 1}u]"
            elif layout == "f":
                s += f"""            {{
                float2 b0 = fb{comp}.{'xy' if g == 0 else 'zw'};
                float2 b1 = fb{comp + 4}.{'xy' if g == 0 else 'zw'};
                float4 fa = WF[(ab + {comp}u) * 3u + {g}u];
                _104 = fma(fa.y, b0.y, fma(fa.x, b0.x, _104));
                _105 = fma(fa.y, b1.y, fma(fa.x, b1.x, _105));
                _106 = fma(fa.w, b0.y, fma(fa.z, b0.x, _106));
                _107 = fma(fa.w, b1.y, fma(fa.z, b1.x, _107));
            }}
"""
                continue
            else:
                b0 = f"WB[bb + {comp}u].{'xy'[g]}"; b1 = f"WB[bb + {comp + 4}u].{'xy'[g]}"
                a0 = f"av{comp}.{'xz'[g]}"; a1 = f"av{comp}.{'yw'[g]}"
            s += f"""            {{
                float2 b0 = float2(as_type<half2>({b0}));
                float2 b1 = float2(as_type<half2>({b1}));
                float2 a0 = float2(as_type<half2>({a0}));
                _104 = fma(a0.y, b0.y, fma(a0.x, b0.x, _104));
                _105 = fma(a0.y, b1.y, fma(a0.x, b1.x, _105));
                float2 a1 = float2(as_type<half2>({a1}));
                _106 = fma(a1.y, b0.y, fma(a1.x, b0.x, _106));
                _107 = fma(a1.y, b1.y, fma(a1.x, b1.x, _107));
            }}
"""
        return "        {\n" + s + rounding + "        }\n"
    if layout == "s6":
        store = """    threadgroup uint* W = hmS + hmSg * 192u;
    W[lane * 6u + 0u] = _98.x; W[lane * 6u + 1u] = _98.y; W[lane * 6u + 2u] = _98.z; W[lane * 6u + 3u] = _98.w;
    W[lane * 6u + 4u] = _99.x; W[lane * 6u + 5u] = _99.y;
"""
        load = ""
    elif layout == "f":
        store = """    threadgroup float4* WF = (threadgroup float4*)(hmS + hmSg * 384u);
    WF[lane * 3u] = float4(float2(as_type<half2>(_98.x)), float2(as_type<half2>(_98.y)));
    WF[lane * 3u + 1u] = float4(float2(as_type<half2>(_98.z)), float2(as_type<half2>(_98.w)));
    WF[lane * 3u + 2u] = float4(float2(as_type<half2>(_99.x)), float2(as_type<half2>(_99.y)));
"""
        load = "".join(f"    float4 fb{c} = WF[(bb + {c}u) * 3u + 2u];\n" for c in range(8))
    else:
        store = """    threadgroup uint4* WA = (threadgroup uint4*)(hmS + hmSg * 192u);
    threadgroup uint2* WB = (threadgroup uint2*)(hmS + hmSg * 192u + 128u);
    WA[lane] = _98; WB[lane] = _99;
"""
        load = "".join(f"    uint4 av{c} = WA[ab + {c}u];\n" for c in range(4))
    return f"""static inline __attribute__((always_inline))
uint2 NAME(uint4 _98, uint2 _99, uint2 _100, thread uint& gl_SubgroupInvocationID, threadgroup uint* hmS, uint hmSg)
{{
    float2 _117 = float2(as_type<half2>(_100.x));
    float _104 = _117.x;
    float _105 = _117.y;
    float2 _120 = float2(as_type<half2>(_100.y));
    float _106 = _120.x;
    float _107 = _120.y;
    uint lane = gl_SubgroupInvocationID & 31u;
    uint ab = lane & 28u;
    uint bb = (lane & 3u) << 3u;
{store}    {B};
{load}{grp(0)}{grp(1)}    {B if tail else ""};
    return uint2(as_type<uint>(half2(float2(_104, _105))), as_type<uint>(half2(float2(_106, _107))));
}}
"""
variants = {"mem-s6": body(), "mem-s6-notail": body(tail=False), "mem-v": body("v"), "mem-v-notail": body("v", tail=False),
            "mem-v-native": body("v", rnd="native"), "mem-v-native-notail": body("v", tail=False, rnd="native"),
            "mem-s6-tg": body(barrier="tg"), "mem-f": body("f"), "mem-f-notail": body("f", tail=False)}

def apply(fn_text):
    s = src[:a] + fn_text.replace("NAME", "_97") + src[b:]
    n0 = s.count("gl_SubgroupInvocationID)")
    # every call site passes gl_SubgroupInvocationID last; the definition was already rewritten
    s = s.replace("gl_SubgroupInvocationID)", "gl_SubgroupInvocationID, hmS, hmSg)")
    assert s.count("uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]])") == 1
    s = s.replace("uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]])",
                  "uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]], uint hmSg [[simdgroup_index_in_threadgroup]])")
    k = s.index("    threadgroup spvUnsafeArray<uint, 1408> _39;")
    s = s[:k] + "    threadgroup uint hmSa[1536];\n    threadgroup uint* hmS = hmSa;\n" + s[k:]
    return s
open(f"{out}/orig.metal", "w").write(src)
for name, fn in variants.items():
    open(f"{out}/{name}.metal", "w").write(apply(fn))

# unit test: header (templates) + original + replacements + kernel
hdr = src[:a]
hdr = hdr[:hdr.index("struct cs_cbuf_block_5u")] if "struct cs_cbuf_block_5u" in hdr[:hdr.index("uint2 _97") if "uint2 _97" in hdr else len(hdr)] else hdr
unit = src[:a] + orig_fn
for i, (name, fn) in enumerate(variants.items()):
    unit += fn.replace("NAME", f"hm{i}")
unit += """
kernel void unit(const device uint* in [[buffer(0)]], device uint* outp [[buffer(1)]], uint3 gid [[thread_position_in_grid]],
                 uint gl_SubgroupInvocationID_ [[thread_index_in_simdgroup]], uint hmSg [[simdgroup_index_in_threadgroup]])
{
    threadgroup uint hmSa[1536];
    threadgroup uint* hmS = hmSa;
    uint gl_SubgroupInvocationID = gl_SubgroupInvocationID_;
    uint t = gid.x;
    uint4 A = uint4(in[t * 8u], in[t * 8u + 1u], in[t * 8u + 2u], in[t * 8u + 3u]);
    uint2 B = uint2(in[t * 8u + 4u], in[t * 8u + 5u]);
    uint2 C = uint2(in[t * 8u + 6u], in[t * 8u + 7u]);
    uint2 r = _97(A, B, C, gl_SubgroupInvocationID);
    outp[t * 24u] = r.x; outp[t * 24u + 1u] = r.y;
""" + "".join(f"    {{ uint2 v = hm{i}(A, B, C, gl_SubgroupInvocationID, hmS, hmSg); outp[t * 24u + {2 + 2 * i}u] = v.x; outp[t * 24u + {3 + 2 * i}u] = v.y; }}\n"
              for i in range(len(variants))) + "    outp[t * 24u + 22u] = gl_SubgroupInvocationID; outp[t * 24u + 23u] = hmSg;\n}\n"
open(f"{out}/unit.metal", "w").write(unit)
open(f"{out}/variants.txt", "w").write("\n".join(variants) + "\n")
print("variants:", ", ".join(variants), "| _97 call sites:", src.count("_97(") - 1, "| last call line:", max(i for i, l in enumerate(src.split('\n'), 1) if "_97(" in l))
