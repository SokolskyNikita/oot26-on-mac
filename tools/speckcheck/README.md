# speckcheck: measuring and replaying rendering faults (the white specks)

Write-up: [../../research/mesh-white-specks/README.md](../../research/mesh-white-specks/README.md).

| File | What |
| --- | --- |
| `speckhunt.py` | The steps of the harness's `at_end` spec key (run a spec with `../harness/queue.sh`), done once Link stands at the end of the walk: `burst` (N screenshots, each scored), `call` (a debug-server call), `frames`, `reject_each` (reject shader groups and burst), `watch_written` |
| `whitecount.py` | Speck score: share of pixels with R, G, B ≥ 235 with the HUD masked; a frame counts as speckled above 0.3 %. `python whitecount.py DIR…` scores folders of PNGs |
| `speck_report.py` | One line per run from `at_end` results |
| `shotwatch.py OUT_DIR` | Watches a running Lichii for a wrong picture, beside any harness batch (it starts no emulator and takes no lock): asks the frame hook for a window capture ten times a second, scores each (`../harness/persist.py`), keeps only the captures with at least 0.5 % clipped white after presented frame 1,500, and writes a line per capture to `shots.csv`. `--on-bad` takes a bug bundle and a 60-present GPU trace through the debug server the first time ten captures in a row are bad in one boot. A clean Kokiri Forest scene scores 0.0 %; the canopy shards of KNOWN-ISSUES KI-29 score 2.6-2.8 % |
| `replay.sh LABEL [ENV=VALUE…]` | Replays the recorded GPU trace offline (no game, no lock) with a Lichii `eden-cli` that has `--replay`, and counts speckled frames. Its default paths point at local build trees that are not part of this repository |
| `msl_variant.py` | Makes `MVK_DIAG_OVERRIDE_DIR` swap pairs (`.orig.metal` / `.repl.metal`) to test edited Metal shader source without rebuilding MoltenVK |
| `diag_payload.py` | Decodes the mesh payload/group readbacks used in the diagnosis |
| `mtlspy/mtlspy.m` | Metal logger injected into the replay (`libmtlspy.dylib`): bindings, argument-buffer contents, `useResource`, raster state; can force state |
| `patches/upstream/moltenvk-mesh-cull-mode.patch` (repository root) | The fix (MoltenVK `MVKPipeline.mm`); the same as `patches/moltenvk/0010-…` |
| `specs/wall-burst.json` | The regression check: 30 scored screenshots at the cave wall, where Link stops at `WALL=(21.3, 109.95, 14.22)` (0 of 30 speckled expected). The investigation's own specs are not kept; their runs' `result.json` files hold them |
