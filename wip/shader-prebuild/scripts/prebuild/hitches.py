"""hitches.py RUN_DIR...: long frames per phase of a verify run (frames.bin + marks in meta.json)."""
import sys, json, struct, statistics as S
for run in sys.argv[1:]:
    meta = json.load(open(run + '/meta.json')); b = open(run + '/frames.bin', 'rb').read()
    t = struct.unpack(f'<{len(b)//8}Q', b); marks = {m['name']: m['frame'] for m in meta.get('marks', [])}
    def fr(m):
        return marks.get(m)
    pts = [(m, fr(m)) for m in ('spawn-seen', 'loaded-standing', 'walk1', 'walk2') if fr(m) is not None] + [('end', len(t) - 1)]
    print(run.split('/')[-1], meta.get('outcome'), 'frames', len(t), 'launch-to-first-frame s', round((t[0] - meta['launch_uptime_ns']) / 1e9, 1) if t else None)
    segs = [('boot+menus', 0, pts[0][1])] + [(pts[i][0], pts[i][1], pts[i + 1][1]) for i in range(len(pts) - 1)]
    for name, a, z in segs:
        d = [(t[i + 1] - t[i]) / 1e6 for i in range(a, min(z, len(t) - 1))]
        if not d: continue
        print(f"  {name:16} frames {len(d):5}  wall {sum(d)/1000:6.1f} s  median {S.median(d):5.1f} ms  >33ms {sum(x>33 for x in d):4}  >70ms {sum(x>70 for x in d):4}  >250ms {sum(x>250 for x in d):3}  worst {max(d):7.0f} ms  time over 33ms {sum(x-33 for x in d if x>33)/1000:6.1f} s")
