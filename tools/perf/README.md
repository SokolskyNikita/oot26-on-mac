# perf: the scripts of the path-to-60fps work

The scripts behind [path-to-60fps](../../research/path-to-60fps/README.md) ("path-60" for short, which is also the
prefix of its patches and of the `P60_*` / `MVK_P60_*` switches). They were written for that work's local build
tree, which held the Lichii and MoltenVK sources, the built apps and the run folders and is not part of this
repository. They are kept as they were.

- The analysis scripts (`cmp.py`, `modecmp.py`, `perframe.py`, `sigdiff.py`) read frame-profile runs from the folder
  in `OOT26_PERF_DIR` (default `build/perf/`). The queue scripts that produced those runs are not kept: the build
  tree they drove is gone, and `tools/harness/` replaces them.
- `hmma/` has the sources of the upscale-kernel tools (`hmtime.swift`, `mkvariants.py`, `mkcse.py`). The built
  `hmtime`, the generated variants and the captured frames (game data) are not in this repository.
- `patches/upstream/moltenvk-mesh-cull-mode.patch` (repository root) is the cull-mode fix as a plain diff; the
  same change is `patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch` in the series.

| Script | What it does |
| --- | --- |
| `tg_audit.py DUMP_DIR` | sums the threadgroup memory each dumped Metal mesh or object shader declares (`MVK_CONFIG_SHADER_DUMP_DIR` dump) |
| `cmp.py LABEL...` | one row per run: standing median, GPU busy and idle, command buffers, encoders |
| `perframe.py`, `sigdiff.py`, `modecmp.py` | per-frame, per-signal and per-mode comparisons of profiler output |
| `gapctx.py`, `gaptrace.py`, `gapsplit.py` | GPU idle gaps against Lichii's sync trace |
