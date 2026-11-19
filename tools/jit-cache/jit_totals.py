#!/usr/bin/env python3
"""jit_totals.py RUNS_DIR: per run of an A/B batch, the JIT cache's diagnostic totals summed over the cores, taken
from the last "JIT totals" line of each core at the end of the load (log time <= load_s, which counts from the launch) and at the
end of the run."""
import glob, json, os, re, sys
KEYS = ['blocks', 'compile_ms', 'lookups', 'lookup_hits', 'lookup_wait_ms', 'emit_wait_ms', 'emit_hold_ms', 'discarded',
        'discarded_ms', 'with_company', 'inval_requests', 'inval_blocks', 'fastmem_recompiles', 'fastmem_stale',
        'fastmem_faults', 'fault_handler_ms', 'fault_wait_ms', 'clears', 'veneers']
def totals(log, until):
    last = {}
    for l in open(log, errors='replace'):
        m = re.match(r'\[\s*([\d.]+)\].*JIT totals core=(\d+) (.*)', l)
        if not m or float(m[1]) > until: continue
        last[int(m[2])] = dict((k, float(v)) for k, v in (kv.split('=') for kv in m[3].split()))
    return {k: sum(c.get(k, 0) for c in last.values()) for k in KEYS}, len(last)
for p in sorted(glob.glob(sys.argv[1] + '/*/result.json'), key=os.path.getmtime):
    r = json.load(open(p)); log = os.path.dirname(p) + '/eden_log.txt'
    if not os.path.exists(log): continue
    end_load = (r.get('load_s') or 0) + 1  # load_s runs from the launch to the end of the load
    for name, until in (('end of load', end_load), ('end of run', 1e9)):
        t, cores = totals(log, until)
        if not cores: continue
        print(f"{r['label']:18s} {name:11s} load {r.get('load_s')} s, {cores} cores: " + ' '.join(f"{k}={t[k]:.0f}" for k in KEYS))
