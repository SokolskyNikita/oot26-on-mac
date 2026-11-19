#!/usr/bin/env python3
"""msl_variant.py SRC.metal OUTDIR VARIANT: write OUTDIR/v.orig.metal (SRC as is) and OUTDIR/v.repl.metal (edited),
the pair MoltenVK's MVK_DIAG_OVERRIDE_DIR swaps in when a shader's generated source equals the original exactly.
Variants (for a mesh shader):
  same       no change (checks that the override is applied and changes nothing)
  zero       every threadgroup array and counter zeroed at entry, before the program body runs
  noatomic   each atomic_fetch_add on guest memory replaced by an atomic load (the shader no longer writes counters)
  none       the shader emits no triangles at all (checks that an edit really reaches the screen)
  nostore    as noatomic, and every plain store to a storage buffer (ssboN... = ...) removed
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(); out = Path(sys.argv[2]); variant = sys.argv[3]
out.mkdir(parents=True, exist_ok=True)
s = src
if variant == "zero":
    decls = re.findall(r"^    threadgroup spvUnsafeArray<(\w+), (\d+)> (\w+);$", s, re.M)
    scalars = re.findall(r"^    threadgroup uint (\w+);$", s, re.M)
    lines = ["    // variant zero: clear the threadgroup memory Metal leaves as the previous threadgroup wrote it"]
    for typ, n, name in decls:
        zero = {"uint": "0u", "uint3": "uint3(0u)", "float4": "float4(0.0)"}[typ]
        lines.append(f"    for (uint spvZ = gl_LocalInvocationIndex; spvZ < {n}u; spvZ += 32u) {{ {name}[spvZ] = {zero}; }}")
    for name in scalars:
        lines.append(f"    if (gl_LocalInvocationIndex == 0) {name} = 0u;")
    lines.append("    threadgroup_barrier(mem_flags::mem_threadgroup);")
    anchor = "    if (gl_LocalInvocationIndex == 0) spvMeshSizes.y = 0u;\n"
    assert s.count(anchor) == 1
    s = s.replace(anchor, anchor + "\n".join(lines) + "\n")
elif variant in ("noatomic", "nostore"):
    s, n = re.subn(r"atomic_fetch_add_explicit\(\(device atomic_uint\*\)&(.*?), [^,]+?, memory_order_relaxed\);",
                   r"atomic_load_explicit((device atomic_uint*)&\1, memory_order_relaxed);", s)
    print("atomic adds replaced:", n)
    if variant == "nostore":
        s, m = re.subn(r"^\s*ssbo\w+\._m0\[.*\] = .*;\n", "", s, flags=re.M)
        print("stores removed:", m)
elif variant == "none":
    anchor = "    spvMesh.set_primitive_count(spvMeshSizes.y);\n"
    assert s.count(anchor) == 1
    s = s.replace(anchor, "    spvMesh.set_primitive_count(0u);\n    return;\n")
elif variant != "same":
    raise SystemExit("unknown variant")
(out / "v.orig.metal").write_text(src); (out / "v.repl.metal").write_text(s)
print(variant, "changed" if s != src else "unchanged", len(src), "->", len(s))
