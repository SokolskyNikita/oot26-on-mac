"""subset.py IN.nx2prep CACHE.bin OUT.nx2prep: keep the compute records and the graphics records whose shader set
(the six program hashes) some pipeline of CACHE uses. Environments are kept as they are."""
import sys, struct
import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
sys.path.insert(0, REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py')
import lichii_cache as lc
want = set()
_, recs = lc.parse_cache(open(sys.argv[2], 'rb').read(), mesh_fields=True)
for r in recs:
    if not r.is_compute: want.add(r.key[:48])
data = open(sys.argv[1], 'rb').read()
magic, version, env_count, record_count, res = struct.unpack_from('<8sIIII', data, 0)
index = [struct.unpack_from('<QQ', data, 24 + 16 * i) for i in range(env_count)]
off = 24 + 16 * env_count; body = bytearray(); kept = 0; g = 0
for _ in range(record_count):
    kind, count, _ = struct.unpack_from('<BBH', data, off); n = 4 + 4 * count + (24 if kind == 1 else 1056)
    rec = data[off:off + n]; off += n
    if kind == 1 or rec[4 + 4 * count:4 + 4 * count + 48] in want:
        body += rec; kept += 1; g += kind == 0
old_start = off; new_start = 24 + 16 * env_count + len(body)
with open(sys.argv[3], 'wb') as f:
    f.write(struct.pack('<8sIIII', magic, version, env_count, kept, res))
    for o, s in index: f.write(struct.pack('<QQ', o - old_start + new_start, s))
    f.write(body); f.write(data[old_start:])
print(f"kept {kept} of {record_count} records ({g} graphics) for {len(want)} shader sets")
