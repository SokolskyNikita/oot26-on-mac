"""summ2.py < fsx2 output: per (data, cfg, coord pattern) min/median for asgen and notex, texture share, rep-to-rep spread."""
import sys, re, collections, statistics as st
R = collections.defaultdict(list)
for l in sys.stdin:
    m = re.match(r'T rep (\d+) data (\S+) cfg (\S+) var (\S+) min ([\d.]+) med ([\d.]+)', l)
    if m: R[(m[2], m[3], m[4].split(':')[0])].append((float(m[5]), float(m[6])))
datas = list(dict.fromkeys(k[0] for k in R)); cfgs = list(dict.fromkeys(k[1] for k in R))
coords = [c for c in ['', '_inc', '_pix', '_mag'] if any(k[2] == 'asgen' + c for k in R)]
print(f"{'data':8s} {'cfg':10s} {'coords':6s} | {'asgen min':>9s} {'med':>6s} {'spread':>6s} | {'notex min':>9s} {'med':>6s} {'spread':>6s} | share(min) share(med) | reps")
for d in datas:
    for c in cfgs:
        for co in coords:
            a = R.get((d, c, 'asgen' + co)); n = R.get((d, c, 'notex' + co))
            if not a or not n: continue
            am, amed, asp = min(x[0] for x in a), st.median(x[1] for x in a), max(x[0] for x in a) - min(x[0] for x in a)
            nm, nmed, nsp = min(x[0] for x in n), st.median(x[1] for x in n), max(x[0] for x in n) - min(x[0] for x in n)
            print(f"{d:8s} {c:10s} {co[1:] or 'base':6s} | {am:9.3f} {amed:6.3f} {asp:6.3f} | {nm:9.3f} {nmed:6.3f} {nsp:6.3f} | {100*(am-nm)/am:9.1f}% {100*(amed-nmed)/amed:9.1f}% | {len(a)},{len(n)}")
