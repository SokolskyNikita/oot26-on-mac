# perf: tracked copies of the path-60 scripts

The path-to-60fps work (`research/path-to-60fps/README.md`) was done in `build/old-trees/path-60/`,
which is git-ignored because it holds the Lichii and MoltenVK build trees and the built apps. The scripts that
existed only there were copied here on 2026-11-18 so they are kept in the repo. The copies are
unchanged, except the link to the write-up in `path-60-README.md`.

- The scripts use absolute paths into `build/old-trees/path-60/` (its `runs/`, `q.sh`, `build.sh`, the build
  trees), so they work from here only while that folder exists. `q.sh` still refers to `../aio-profile/run_full.sh`
  for `full` runs, and that folder has since been deleted.
- `path-60-README.md` is that folder's own README: what each switch, script and app is.
- `hmma/` has the sources of the upscale-kernel tools (`hmtime.swift`, `mkvariants.py`, `mkcse.py`). The built
  `hmtime`, the generated variants (`v/`) and the captured frames (`real/`, `real-hm/`, game data) stay in
  `path-60/hmma/`.
- `patches/upstream/moltenvk-mesh-cull-mode.patch` is already tracked, byte for byte, as
  `patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch`.

| Script | What it does |
| --- | --- |
| `q.sh` | queue of `sc-update/run.sh` lines (`full ` prefix for the whole route) |
| `runq.sh FILE` | same, waiting for the emulator to exit between runs |
| `seedq.sh` | copies one config's caches to new configs, then runs the queue |
| `cfgrun.sh` | runs with a changed global setting and restores it afterwards |
| `rest.sh`, `reorder.sh`, `pgo-llvm-pipeline.sh` | one-off queues for the PGO, LTO and LLVM builds and the debugsrv batches |
| `cmp.py LABEL...` | one row per run: standing median, GPU busy and idle, command buffers, encoders |
| `perframe.py`, `sigdiff.py`, `modecmp.py` | per-frame, per-signal and per-mode comparisons of profiler output |
| `gapctx.py`, `gaptrace.py`, `gapsplit.py` | GPU idle gaps against Lichii's sync trace |
