# perf: tools of the path-to-60fps work

Tools of [path-to-60fps](../../research/path-to-60fps/README.md) ("path-60" for short, which is also the prefix of
its patches and of the `P60_*` / `MVK_P60_*` switches). The readers of the MoltenVK frame profiler and Lichii's sync
trace (per frame, per signature, GPU idle gaps against the sync events) are `tools/diag/gpu.py`
([`../diag`](../diag/README.md)), which reads them from a harness run folder.

- `hmma/` has the sources of the upscale-kernel tools (`hmtime.swift`, `mkvariants.py`, `mkcse.py`). The built
  `hmtime`, the generated variants and the captured frames (game data) are not in this repository.
- `patches/upstream/moltenvk-mesh-cull-mode.patch` (repository root) is the cull-mode fix as a plain diff; the
  same change is `patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch` in the series.

| Script | What it does |
| --- | --- |
| `tg_audit.py DUMP_DIR` | sums the threadgroup memory each dumped Metal mesh or object shader declares (`MVK_CONFIG_SHADER_DUMP_DIR` dump) |
