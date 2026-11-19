# perf: the scripts of the path-to-60fps work

The scripts behind [path-to-60fps](../../research/path-to-60fps/README.md) ("path-60" for short, which is also the
prefix of its patches and of the `P60_*` / `MVK_P60_*` switches). They were written for that work's local build
tree, which held the Lichii and MoltenVK sources, the built apps and the run folders and is not part of this
repository. They are kept as they were.

- The scripts use absolute paths into that build tree (its `runs/`, `q.sh`, `build.sh`, the source trees), so they
  run only where that layout exists. `q.sh` also calls a full-route run script for `full` runs that is not kept.
- `hmma/` has the sources of the upscale-kernel tools (`hmtime.swift`, `mkvariants.py`, `mkcse.py`). The built
  `hmtime`, the generated variants and the captured frames (game data) are not in this repository.
- `patches/upstream/moltenvk-mesh-cull-mode.patch` (repository root) is the cull-mode fix as a plain diff; the
  same change is `patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch` in the series.

| Script | What it does |
| --- | --- |
| `q.sh` | queue of run-script lines (`full ` prefix for the whole route); the run script is kept as [run.sh.txt](../../research/mac-performance/patches/run.sh.txt) |
| `runq.sh FILE` | same, waiting for the emulator to exit between runs |
| `seedq.sh` | copies one config's caches to new configs, then runs the queue |
| `cfgrun.sh` | runs with a changed global setting and restores it afterwards |
| `rest.sh`, `reorder.sh`, `pgo-llvm-pipeline.sh` | one-off queues for the PGO, LTO and LLVM builds and the harness batches |
| `cmp.py LABEL...` | one row per run: standing median, GPU busy and idle, command buffers, encoders |
| `perframe.py`, `sigdiff.py`, `modecmp.py` | per-frame, per-signal and per-mode comparisons of profiler output |
| `gapctx.py`, `gaptrace.py`, `gapsplit.py` | GPU idle gaps against Lichii's sync trace |
