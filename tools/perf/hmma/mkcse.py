#!/usr/bin/env python3
"""mkcse.py DUMP.metal OUT.metal [--notail]: the shuffle-free HMMA with the gathers shared between multiplies.
The multiply is split into gather(A) (a lane fetches the 4 uint4 of its A row block), gather(B) (the 8 uint2 of its B
column block) and the arithmetic. A gather of the same operand expression is done once and reused (all call sites are in
one straight-line block and the operands are SSA temporaries or loads from read-only buffers)."""
import re, sys
src = open(sys.argv[1]).read(); tail = "--notail" not in sys.argv
a = src.index("static inline __attribute__((always_inline))\nuint2 _97("); b = src.index("\n}\n", a) + 3
fn = src[a:b]
ROUND = fn[fn.index("            uint _316"):fn.index("            _102 = _136 + 1u;")]
SB = "simdgroup_barrier(mem_flags::mem_threadgroup);"
def grp(g):
    s = "    {\n"
    for comp in range(4):
        s += f"""        {{
            float2 b0 = float2(as_type<half2>(gb.c[{comp}].{'xy'[g]}));
            float2 b1 = float2(as_type<half2>(gb.c[{comp + 4}].{'xy'[g]}));
            float2 a0 = float2(as_type<half2>(ga.r[{comp}].{'xz'[g]}));
            _104 = fma(a0.y, b0.y, fma(a0.x, b0.x, _104));
            _105 = fma(a0.y, b1.y, fma(a0.x, b1.x, _105));
            float2 a1 = float2(as_type<half2>(ga.r[{comp}].{'yw'[g]}));
            _106 = fma(a1.y, b0.y, fma(a1.x, b0.x, _106));
            _107 = fma(a1.y, b1.y, fma(a1.x, b1.x, _107));
        }}
"""
    return s + ROUND + "    }\n"
helpers = f"""struct HA {{ uint4 r[4]; }};
struct HB {{ uint2 c[8]; }};
static inline __attribute__((always_inline))
HA hmGA(uint4 v, uint lane_, threadgroup uint* hmS, uint hmSg)
{{
    uint lane = lane_ & 31u;
    threadgroup uint4* W = (threadgroup uint4*)(hmS + hmSg * 192u);
    W[lane] = v;
    {SB}
    uint ab = lane & 28u;
    HA g; g.r[0] = W[ab]; g.r[1] = W[ab + 1u]; g.r[2] = W[ab + 2u]; g.r[3] = W[ab + 3u];
    {SB if tail else ""}
    return g;
}}
static inline __attribute__((always_inline))
HB hmGB(uint2 v, uint lane_, threadgroup uint* hmS, uint hmSg)
{{
    uint lane = lane_ & 31u;
    threadgroup uint2* W = (threadgroup uint2*)(hmS + hmSg * 192u + 128u);
    W[lane] = v;
    {SB}
    uint bb = (lane & 3u) << 3u;
    HB g; for (uint i = 0u; i < 8u; i++) g.c[i] = W[bb + i];
    {SB if tail else ""}
    return g;
}}
static inline __attribute__((always_inline))
uint2 hmMul(HA ga, HB gb, uint2 _100)
{{
    float2 _117 = float2(as_type<half2>(_100.x));
    float _104 = _117.x;
    float _105 = _117.y;
    float2 _120 = float2(as_type<half2>(_100.y));
    float _106 = _120.x;
    float _107 = _120.y;
{grp(0)}{grp(1)}    return uint2(as_type<uint>(half2(float2(_104, _105))), as_type<uint>(half2(float2(_106, _107))));
}}
"""
body = src[b:]
memo = {}; stats = {"calls": 0}
def split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([": depth += 1
        if ch in ")]": depth -= 1
        if ch == "," and depth == 0: out.append(cur.strip()); cur = ""
        else: cur += ch
    out.append(cur.strip()); return out
def rewrite_expr(e, pre):
    """Replace every _97(...) in e (innermost first through C), adding gather declarations to pre."""
    while True:
        i = e.find("_97(")
        if i < 0: return e
        j = i + 4; depth = 1
        while depth: depth += {"(": 1, ")": -1}.get(e[j], 0); j += 1
        A, B, C, _ = split_args(e[i + 4:j - 1])
        A = rewrite_expr(A, pre); B = rewrite_expr(B, pre); C = rewrite_expr(C, pre)
        names = []
        for kind, ex, f in (("A", A, "hmGA"), ("B", B, "hmGB")):
            key = (kind, re.sub(r"\s+", "", ex))
            if key not in memo:
                memo[key] = f"hm{kind}{len(memo)}"
                pre.append(f"    H{kind} {memo[key]} = {f}({ex}, gl_SubgroupInvocationID, hmS, hmSg);\n")
            names.append(memo[key])
        stats["calls"] += 1
        e = e[:i] + f"hmMul({names[0]}, {names[1]}, {C})" + e[j:]
lines = body.split("\n"); out = []
for ln in lines:
    if "_97(" in ln:
        pre = []; ln = rewrite_expr(ln, pre); out.extend(p.rstrip("\n") for p in pre)
    out.append(ln)
body = "\n".join(out)
assert body.count("uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]])") == 1
body = body.replace("uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]])",
                    "uint gl_SubgroupInvocationID [[thread_index_in_simdgroup]], uint hmSg [[simdgroup_index_in_threadgroup]])")
k = body.index("    threadgroup spvUnsafeArray<uint, 1408> _39;")
body = body[:k] + "    threadgroup uint hmSa[768];\n    threadgroup uint* hmS = hmSa;\n" + body[k:]
open(sys.argv[2], "w").write(src[:a] + helpers + body)
print(f"multiplies {stats['calls']}, gathers of A {sum(k[0] == 'A' for k in memo)}, of B {sum(k[0] == 'B' for k in memo)}")
