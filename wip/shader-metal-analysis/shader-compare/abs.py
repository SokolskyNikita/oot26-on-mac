"""abs.py RUNFILE: per dir and rep, min/median ms (summed over the 8 data sets, best of the two order slots per form),
direct-vs-argbuf % and bit-identity. Also an A/A noise estimate from the two slots of the same form."""
import re, sys, collections, statistics as st
R = collections.defaultdict(lambda: collections.defaultdict(list)); diffs = collections.Counter(); key = None
for l in open(sys.argv[1]):
    m = re.match(r'=== rep (\d+) dir (\S+)', l)
    if m: key = (m.group(2), int(m.group(1))); continue
    m = re.match(r'(\S+?):safe:8:blend\s+median\s+([\d.]+) ms\s+min\s+([\d.]+) \|.*\| (.*)', l)
    if not m: continue
    R[key][m.group(1)].append((float(m.group(3)), float(m.group(2))))
    d = re.search(r'differing\s+(\d+)', m.group(4))
    if d and int(d.group(1)): diffs[(key[0], m.group(1))] += 1
print(f"{'dir':6} {'rep':>3} | {'asgen min':>9} {'asgen_d':>8} {'d%':>6} | {'all min':>8} {'all_d':>8} {'d%':>6} | {'asgen med':>9} {'asgen_d':>8} {'d%':>6} | {'all med':>8} {'all_d':>8} {'d%':>6} | A/A %")
agg = collections.defaultdict(list)
for (d, r), v in sorted(R.items()):
    # each label appears twice per data set (16 entries: slot A then slot B per data set, in order)
    def tot(lab, i, slot=None):
        xs = v[lab]; pairs = [xs[k:k+2] for k in range(0, len(xs), 2)]
        return sum((min(p[0][i], p[1][i]) if slot is None else p[slot][i]) for p in pairs) / len(pairs)
    row = []; 
    for i in (0, 1):
        for b in ('asgen', 'all'):
            a, x = tot(b, i), tot(b + '_d', i); row += [a, x, 100 * (x - a) / a]; agg[(d, b, i)].append(100 * (x - a) / a)
    aa = [100 * (tot(b, 0, 1) - tot(b, 0, 0)) / tot(b, 0, 0) for b in ('asgen', 'asgen_d', 'all', 'all_d')]
    agg[(d, 'aa')].extend(aa)
    print(f"{d:6} {r:3} | " + ' | '.join(f"{row[k]:9.3f} {row[k+1]:8.3f} {row[k+2]:+6.1f}" for k in range(0, 12, 3)) + ' | ' + ' '.join(f'{x:+.1f}' for x in aa))
print('\nmean ms per pass-set = average over the 8 data sets of the per-data-set value (8 blended 1080p passes)')
for d in sorted({k[0] for k in agg}):
    s = lambda k: f"{st.mean(agg[k]):+.1f}% (range {min(agg[k]):+.1f}..{max(agg[k]):+.1f})"
    print(f"{d}: direct vs argbuf, min: asgen {s((d,'asgen',0))}, all {s((d,'all',0))}; median: asgen {s((d,'asgen',1))}, all {s((d,'all',1))}; A/A slot noise (min) {s((d,'aa'))}")
print('non-identical pixel results:', dict(diffs) or 'none')
