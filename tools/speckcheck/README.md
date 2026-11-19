# speckcheck: measuring and replaying rendering faults (the white specks)

Write-up: [../../research/mesh-white-specks/README.md](../../research/mesh-white-specks/README.md).

| File | What |
| --- | --- |
| `speck_run.sh SPEC.json` | Runs a spec with the A/B harness (`tools/harness/ab.py`, patched into `ab_at_end.py` here) plus an `at_end` key: steps run once Link stands at the end of the walk. Use an absolute spec path. Waits for the emulator lock |
| `speckhunt.py` | The `at_end` steps: `burst` (N screenshots, each scored), `call` (a debug-server call), `frames`, `reject_each` (reject shader groups and burst), `watch_written` |
| `whitecount.py` | Speck score: share of pixels with R, G, B ≥ 235 with the HUD masked; a frame counts as speckled above 0.3 %. `python whitecount.py DIR…` scores folders of PNGs |
| `speck_report.py` | One line per run from `at_end` results |
| `replay.sh LABEL [ENV=VALUE…]` | Replays the recorded GPU trace offline (no game, no lock) with a Lichii `eden-cli` that has `--replay`, and counts speckled frames. Its default paths point at local build trees that are not part of this repository |
| `msl_variant.py` | Makes `MVK_DIAG_OVERRIDE_DIR` swap pairs (`.orig.metal` / `.repl.metal`) to test edited Metal shader source without rebuilding MoltenVK |
| `diag_payload.py` | Decodes the mesh payload/group readbacks used in the diagnosis |
| `mtlspy/mtlspy.m` | Metal logger injected into the replay (`libmtlspy.dylib`): bindings, argument-buffer contents, `useResource`, raster state; can force state |
| `patches/upstream/moltenvk-mesh-cull-mode.patch` (repository root) | The fix (MoltenVK `MVKPipeline.mm`); the same as `patches/moltenvk/0010-…` |
| `specs/specks*.json` | The investigation's run specs (cave wall: Link stops at `WALL=(21.3, 109.95, 14.22)`) |
