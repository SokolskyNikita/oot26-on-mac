#!/bin/sh
# speck_run.sh SPEC.json: the A/B harness (tools/harness/ab.py, as it is now) plus an "at_end" spec key, whose
# steps (speckhunt.py) run once Link stands at the end of the walk. Waits for the emulator lock.
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
DBG=$REPO/tools/harness
python3 - "$DBG" "$HERE" <<'PY' || exit 1
import sys
dbg, here = sys.argv[1:]
s = open(dbg + "/ab.py").read()
a = "HERE = Path(__file__).resolve().parent\n"
b = '        title("done")\n        res["outcome"] = "completed"\n'
assert s.count(a) == 1 and s.count(b) == 1, "ab.py changed: update speck_run.sh"
s = s.replace(a, f'HERE = Path("{dbg}")\nsys.path.insert(0, "{here}")\n')
s = s.replace(b, '        if spec.get("at_end"):\n            import speckhunt\n'
                 '            speckhunt.at_end(spec["at_end"], rd, res, call, lambda n: wait_frames(n, alive), title,\n'
                 '                             pos=lambda: pos(actor))\n' + b)
open(here + "/ab_at_end.py", "w").write(s)
PY
cd "$DBG" && exec ../verify/verify.py with-lock --lock-wait 21600 -- uv run -q --with pillow --with numpy python "$HERE/ab_at_end.py" "$1"
