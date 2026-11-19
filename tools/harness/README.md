# debugsrv: driving and measuring Lichii through its debug server

Tools for running the game unattended in Lichii and A/B-testing settings, builds and patches. What they found is in
[../../research/emulator-options/README.md](../../research/emulator-options/README.md).

| File | What |
| --- | --- |
| `ab.py` | The harness: one run per spec entry (waits for this project's builds, boots, loads the save, settles 3 s, walks with turns at walls, stands, measures), results in `runs/` |
| `queue.sh` | `./queue.sh A.json B.json …`: several spec files back to back, each under the emulator lock; `touch PAUSE` makes queues wait (outside the lock) to leave the emulator to other sessions |
| `config.json` | Defaults: which save to load (`save` by map name, or `save_index`), where Link must stand after it, the session name in the window title |
| `dbg.py` | Minimal client for Lichii's debug server (`python3 dbg.py status`, or `from dbg import call`) |
| `uisig.py`, `uiscan.py` | Print the game's UI-manager screens and scene (how the menu states were mapped) |
| `jitlog.py` | `python jitlog.py RUN_DIR`: summary of a per-compile JIT log (`jit.bin`) from `path-60/app-jitlog` run with `EDEN_NX2_JIT_LOG`: phase split, per core, repeats across cores, per-second timeline, modules and pages |
| `stuttercause.py` | `python stuttercause.py RUN_DIR…`: the stutter trace's slow frames per harness phase, by time (JIT, pipeline builds, GPU-side waits) |
| `stutterjit.py` | Older per-phase view of the stutter trace by frame number (game frames, not presents: use `stuttercause.py`) |
| `p95.py` | `python p95.py RUN_DIR…`: p50 / p90 / p95 / p99 / max per phase from `frames.bin`, for runs made before p95 was recorded |
| `../speckcheck/` | Speck tools (screenshot bursts scored for white specks, GPU trace replay); used for the independent check of the mesh cull-mode fix (`specs/val-cull.json`, run with `../speckcheck/speck_run.sh` and an absolute spec path) |
| `session.sh` | One interactive Lichii session with the debug server on, under the lock; `touch STOP` ends it |
| `*.json` (here) | Specs still queued; finished ones are in `specs/`, cancelled ones in `specs/cancelled/` |
| `build-variants/` | Copies of `path-60/prebuild-variants.sh` (LTO, PGO, upstream-LLVM builds), `pgo-pipeline.sh` and `build-mvk-par.sh` (the parallel-shader-compile MoltenVK variants) |
| `patches/` | Changes made to Lichii / MoltenVK in `path-60` (that tree is not in this repo): the JIT flush, keep-encoder on by default, the closed Hypervisor experiments, the per-compile JIT log, the MoltenVK pipeline-cache progress log and the four parallel-compile variants (`moltenvk-<variant>-vs-path60-*.patch`) |
| `shader-refs/mipflow.json` | The shader-analysis session's list of fragment programs with per-pixel conditional samples (kept from a temporary folder) |

## Running

```bash
cd tools/harness
../mvk-mesh/verify/verify.py with-lock -- uv run -q --with pillow --with numpy python ab.py smoke.json
./queue.sh specs/batch3.json             # or several files in one call
```

Needs the DSU pad server running (`../pad/dsu_server.py`: Lichii's player 1 is bound to it) and the verify hook
(`../mvk-mesh/verify/build/libverifyhook.dylib`, built by `verify.py`). The harness edits
`~/.config/lichii/qt-config.ini` per run from the master copy `qt-config.ini.before-debugsrv-2026-11-17` and puts it
back afterwards.

A spec is a JSON list of runs: `label`, `desc`, `cfg` (config keys), `env` (`{rd}` = the run folder), `app`, `args`,
`repeat`, `phase_frames`, `variants`, `server_calls`, `settle_s` (default 3: seconds with no pipeline build before measuring), `walk` (`bounce`, the default: run in 30-frame chunks and turn round when stuck (two quarter turns: left stick right, then a right-stick click to put the camera behind Link; then forward again); `route`: the old fixed route), `stand_first` (add a standing phase before the walk), `cold_metal_cache` (boot from an empty Metal cache, the real one held aside and restored), `save` / `expect_spawn` (another save; null skips the spawn check), `jsdbg` (`attach` / `arm`), `flicker`, `capture`.
Each run folder holds `result.json` (frame statistics per phase, boot and load times, build counts, positions), the
per-present clock `frames.bin`, `eden_log.txt`, screenshots, and on failure a stack sample or screenshot.

Rules the harness follows, from what went wrong: game state comes from memory, never from screenshots; `main`'s
address is read from each boot's log (ASLR); never queue specs as separate waiters on "no queue.sh running" (they
match their own command lines); a debugger attaches only once the guest is held.
