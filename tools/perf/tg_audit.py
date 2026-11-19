"""Sum the threadgroup memory each dumped Metal mesh/object shader declares in its entry point."""
import re, sys, glob, collections
SZ = {'uint':4,'int':4,'float':4,'bool':1,'uint2':8,'int2':8,'float2':8,'uint3':16,'int3':16,'float3':16,
      'uint4':16,'int4':16,'float4':16,'uchar':1,'ushort':2}
decl = re.compile(r'^\s*threadgroup\s+(?:spvUnsafeArray<(\w+),\s*(\d+)>|(\w+))\s+(\w+);', re.M)
rows = []
for f in sorted(glob.glob(sys.argv[1] + '/*.metal')):
    s = open(f).read()
    stage = 'mesh' if '[[mesh]]' in s else 'object' if '[[object]]' in s else None
    if not stage: continue
    total = 0; parts = collections.OrderedDict(); unknown = []
    for t, n, t2, name in decl.findall(s):
        ty = t or t2; cnt = int(n) if n else 1
        if ty not in SZ: unknown.append(ty); continue
        b = SZ[ty] * cnt; total += b
        key = 'outputs' if (name.startswith('gl_Position') or re.fullmatch(r'_\d+', name)) else name
        parts[key] = parts.get(key, 0) + b
    m = re.search(r'mesh<(\w+), (\w+), (\d+), (\d+)', s)
    rows.append((total, stage, f.split('/')[-1], m.groups()[2:] if m else '', dict(parts), unknown))
for r in sorted(rows, reverse=True):
    print(r[0], r[1], r[2], r[3], r[4], r[5] or '')
