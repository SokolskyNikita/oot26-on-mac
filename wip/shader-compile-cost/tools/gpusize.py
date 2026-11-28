"""gpusize.py ARCHIVE: byte size of the fragment and vertex GPU code inside a serialised Metal binary archive."""
import re, subprocess, sys, tempfile, os
a = open(sys.argv[1], "rb").read(); out = {}
for m in re.finditer(b"\xcf\xfa\xed\xfe", a):
    with tempfile.NamedTemporaryFile(delete=False) as t: t.write(a[m.start():m.start() + 0x80000])
    o = subprocess.run(["otool", "-l", t.name], capture_output=True, text=True).stdout; os.unlink(t.name)
    secs = re.findall(r"sectname (\S+)\n\s+segname (\S+)\n\s+addr \S+\n\s+size (\S+)", o)
    text = [int(s, 16) for n, g, s in secs if n == "__text"]
    kind = next((n for n, g, s in secs if n in ("__fragment", "__vertex")), None)
    if kind and text: out[kind] = out.get(kind, 0) + text[0]
print(out.get("__fragment", 0), out.get("__vertex", 0))
