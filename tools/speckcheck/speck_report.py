#!/usr/bin/env python3
"""speck_report.py RUNS_DIR...: one line per run under each ab-* folder with an at_end burst: frames with specks,
mean white share, verdict, and what the run changed (env, cfg, app)."""
import json
import sys
from pathlib import Path

for arg in sys.argv[1:]:
    for f in sorted(Path(arg).glob("*/result.json")):
        j = json.loads(f.read_text()); spec = j.get("spec", {})
        what = dict(spec.get("env", {}), **spec.get("cfg", {}))
        app = Path(spec.get("app", "default")).parent.name
        stand = (j.get("at_end") or {}).get("stand") or {}
        where = (f"{stand['from_wall_m']} m from the wall" + ("" if stand.get("stopped") else ", STILL MOVING")) if stand else ""
        for name, b in (j.get("at_end") or {}).items():
            if "frames" not in b:
                continue
            over = b.get("over")
            verdict = b.get("verdict") or ("specks" if over * 2 > b["frames"] else "clean" if over == 0 else "mixed")
            print(f"{f.parent.parent.name[3:]} {j['label']:<32} {name:<10} {over:>3}/{b['frames']:<3} "
                  f"{b.get('mean_pct', 0):6.3f} %  {verdict:<7} {b.get('via', 'server'):<7} {app} {what or ''}")
