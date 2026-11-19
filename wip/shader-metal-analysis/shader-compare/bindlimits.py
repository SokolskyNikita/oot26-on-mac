"""Count the resources each cached Metal shader takes through its argument buffer(s), against Metal's direct-binding limits."""
import re, glob, collections, sys
S = sys.argv[1]
st = collections.defaultdict(lambda: collections.Counter()); worst = collections.defaultdict(list); hist = collections.defaultdict(collections.Counter)
for f in sorted(glob.glob(S + '/msl/*.metal')):
    t = open(f, errors='replace').read()
    m = re.search(r'^(fragment|vertex|kernel) ', t, re.M)
    if not m: continue
    stage = m.group(1); buf = tex = smp = 0
    for body in re.findall(r'struct spvDescriptorSetBuffer\d+\s*\{(.*?)\n\};', t, re.S):
        for line in body.split('\n'):
            line = line.strip()
            if not line or line.startswith('//') or '_pad' in line: continue
            n = 1; a = re.match(r'array<(.+),\s*(\d+)>', line)
            if a: n = int(a.group(2)); line = a.group(1)
            if re.match(r'(texture|depth)', line): tex += n
            elif line.startswith('sampler'): smp += n
            elif '*' in line: buf += n
            else: st[stage]['unparsed lines'] += 1
    extra = len(re.findall(r'\[\[buffer\((\d+)\)\]\]', t))   # buffers already bound directly (the argument buffers themselves, etc.)
    c = st[stage]; c['shaders'] += 1
    ok_s = smp <= 16; ok_b = buf <= 31; ok_t31 = tex <= 31; ok_t = tex <= 128
    c['fit (16 samplers, 31 buffers, 128 textures)'] += ok_s and ok_b and ok_t
    c['fit even with 31 textures'] += ok_s and ok_b and ok_t31
    c['over 16 samplers'] += not ok_s; c['over 31 buffers'] += not ok_b; c['over 31 textures'] += not ok_t31; c['over 128 textures'] += not ok_t
    c['use no texture at all'] += tex == 0
    hist[stage][min(smp, 65)] += 1
for s, c in st.items():
    print('==', s); [print(f'   {v:5}  {k}') for k, v in c.items()]
    print('   sampler-count histogram:', sorted(hist[s].items()))
