import sys,re,collections
rows=collections.OrderedDict(); mode=None
for l in sys.stdin:
    if l.startswith('--- data'): mode=l.split(': ')[1].strip(); continue
    m=re.match(r'(\S+)\s+median\s+([\d.]+) ms\s+min\s+([\d.]+) \|.*\| (.*)',l)
    if not m: continue
    d=re.search(r'differing\s+(\d+).*>1% off: (\d+), max rel diff ([\d.]+)',m.group(4))
    rows.setdefault(m.group(1)+('#2' if (m.group(1),mode) in seen else ''),[]).append((mode,float(m.group(3)),float(m.group(2)),d.groups() if d else None)) if not (seen:=globals().setdefault('seen',set())) is None else None
    seen.add((m.group(1),mode))
print(f"{'variant':24s} {'min ms: lowest..highest over data sets':40s} worst pixel diff vs reference")
for k,v in rows.items():
    mins=[x[1] for x in v]; ds=[x[3] for x in v if x[3]]
    worst=max(ds,key=lambda t:(int(t[0]),float(t[2]))) if ds else None
    print(f"{k:24s} {min(mins):5.2f} .. {max(mins):5.2f}   mean {sum(mins)/len(mins):5.2f}      "+(f"{worst[0]} px differ, {worst[1]} >1%, max rel {worst[2]}" if worst else 'reference'))
