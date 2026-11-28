"""cmparch.py DIR_A DIR_B...: compare, per shader, the GPU programs inside the binary archives of each directory
against the first. Reports whole-file identity and, per Mach-O object, identity of each section's bytes."""
import sys, os, re, hashlib, subprocess, tempfile
def objs(path):
    a = open(path, "rb").read(); out = []
    for m in re.finditer(b"\xcf\xfa\xed\xfe", a):
        with tempfile.NamedTemporaryFile(delete=False) as t: t.write(a[m.start():m.start() + 0x100000])
        o = subprocess.run(["otool", "-l", t.name], capture_output=True, text=True).stdout
        secs = re.findall(r"sectname (\S+)\n\s+segname (\S+)\n\s+addr \S+\n\s+size (\S+)\n\s+offset (\d+)", o)
        blob = open(t.name, "rb").read(); os.unlink(t.name)
        d = {}
        for n, g, s, off in secs:
            d[g + "," + n] = hashlib.sha1(blob[int(off):int(off) + int(s, 16)]).hexdigest()[:10]
        out.append(d)
    return hashlib.sha1(a).hexdigest()[:10], out
ref = sys.argv[1]; names = sorted(os.listdir(ref))
R = {n: objs(os.path.join(ref, n)) for n in names}
print("reference", ref, "shaders", len(names), "objects per archive", sorted(set(len(v[1]) for v in R.values())))
for d in sys.argv[2:]:
    same_file = same_text = same_all = missing = 0; diffs = {}
    for n in names:
        p = os.path.join(d, n)
        if not os.path.exists(p): missing += 1; continue
        h, o = objs(p)
        same_file += h == R[n][0]
        ro = R[n][1]
        t = len(o) == len(ro) and all(x.get("__TEXT,__text") == y.get("__TEXT,__text") for x, y in zip(o, ro))
        al = len(o) == len(ro) and all(x == y for x, y in zip(o, ro))
        same_text += t; same_all += al
        if not al:
            for x, y in zip(o, ro):
                for k in set(x) | set(y):
                    if x.get(k) != y.get(k): diffs[k] = diffs.get(k, 0) + 1
    print(f"{d}: whole file identical {same_file}/{len(names)}; GPU code identical {same_text}; all sections identical {same_all}; missing {missing}; differing sections {diffs}")
