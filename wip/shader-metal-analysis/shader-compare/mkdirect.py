"""mkdirect.py DIR name...: write DIR/v_<name>_d.metal = DIR/v_<name>.metal with every spvDescriptorSetBuffer0 member bound
directly as a fragment argument. Mapping (must match fsxd.swift): unique buffer ids ascending -> [[buffer(1+k)]],
texture members by id -> [[texture(k)]], sampler members by id -> [[sampler(k)]]."""
import re, sys
d = sys.argv[1]
for name in sys.argv[2:]:
    s = open(f'{d}/v_{name}.metal').read()
    m = re.search(r'struct spvDescriptorSetBuffer0\s*\{(.*?)\n\};\n', s, re.S)
    mem = []
    for line in m.group(1).split('\n'):
        line = line.strip()
        if not line or line.startswith('//'): continue
        t = re.match(r'(.*?)\s*(\w+) \[\[id\((\d+)\)\]\];$', line); assert t, line
        mem.append((int(t.group(3)), t.group(1), t.group(2)))
    mem.sort(); args = []; nb = nt = ns = 0; used = []
    for i, ty, nm in mem:
        if nm.endswith('_pad'): continue
        if ty.startswith('sampler'): args.append(f'{ty} spvD_{nm} [[sampler({ns})]]'); ns += 1
        elif ty.startswith('texture') or ty.startswith('array<'): args.append(f'{ty} spvD_{nm} [[texture({nt})]]'); nt += 1
        else: nb += 1; args.append(f'{ty} spvD_{nm} [[buffer({nb})]]')
        used.append(nm)
    s = s[:m.start()] + s[m.end():]
    s = s.replace('constant spvDescriptorSetBuffer0& spvDescriptorSet0 [[buffer(0)]]', ', '.join(args))
    # aliasing casts: reinterpret_cast<T* constant &>(member) -> reinterpret_cast<T*>(param)
    s, na = re.subn(r'reinterpret_cast<([^<>]*?\*) constant &>\(spvDescriptorSet0\.(\w+)\)', r'reinterpret_cast<\1>(spvD_\2)', s)
    s, nr = re.subn(r'spvDescriptorSet0\.(\w+)', r'spvD_\1', s)
    assert 'spvDescriptorSet' not in s
    open(f'{d}/v_{name}_d.metal', 'w').write(s)
    print(f'{d}/v_{name}_d.metal: {nb} buffers, {nt} textures, {ns} samplers; {na} alias casts, {nr} member uses rewritten')
