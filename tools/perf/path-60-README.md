# path-60: code, patches and scripts for research/path-to-60fps

Write-up: [research/path-to-60fps/README.md](../../research/path-to-60fps/README.md).

- `lichii/`: copy of `../allinone/lichii` with the experiment switches; all are off unless their variable is set.
  `patches/lichii/0006-path-60-frame-time-fixes-and-their-switches.patch` is its diff. `moltenvk/`: copy of `../aio-profile/moltenvk` (all-in-one MoltenVK plus the frame
  profiler) with the switches in `patches/moltenvk/0007-path-60-keep-the-render-encoder-across-barriers-and-.patch`. `build.sh [mvk|lichii|all|asm] APPNAME` builds and assembles
  `APPNAME/lichii.app`; `app-r8` is the last one.
- Switches. Lichii: `P60_HMMA_MEM` (shuffle-free tensor multiply), `P60_OOT_BILINEAR` (with
  `EDEN_NX2_DLSS_REPLACEMENT=fsr`: bilinear stand-in for the upscale pass), `P60_LIST_INDIRECT`, `P60_UINT8_HOST`,
  `P60_RUN_AHEAD`, `P60_SYNC_TRACE=<file>`. MoltenVK: `MVK_P60_KEEP_ENCODER`, `MVK_P60_NO_APPNAP`.
- Runs: `q.sh` (queue of `sc-update/run.sh` lines, `full ` prefix for the whole route), `runq.sh FILE` (same, waiting
  for the emulator to be gone between runs), `seedq.sh` (copy a CFG's caches to new CFGs first), `cfgrun.sh` (runs
  with a changed global setting, restored after). Queues and logs are in `runs/`.
- Reports: `cmp.py LABEL...` (one row per run), `perframe.py`, `sigdiff.py`, `modecmp.py`, `gapctx.py`,
  `gaptrace.py`, `gapsplit.py` (GPU idle gaps against Lichii's sync trace).
- `hmma/`: offline work on the network upscale kernel. `mkvariants.py` and `mkcse.py` write MSL variants,
  `hmtime unit` compares the multiply bit for bit, `hmtime time --real DIR` times variants on a captured frame and
  compares the output image. `real/` and `real-hm/` hold captured inputs (game data: keep private).

## Adopted build (2026-11-16, after the write-up)

- In `lichii/`, `P60_HMMA_MEM`, `P60_UINT8_HOST` and `P60_LIST_INDIRECT` are now on by default; `=0` turns each off.
  The other switches are unchanged (off unless set). `app-adopt/` is that build with path-60's MoltenVK.
- `app-practice/` is a copy of `app-adopt` whose `Info.plist` sets `LSEnvironment` to
  `EDEN_NX2_DLSS_REPLACEMENT=fsr`, `P60_OOT_BILINEAR=1` and `MVK_P60_NO_APPNAP=1`, so a normal launch
  (double-click or `open`) runs with the game's network upscaler replaced by a bilinear resize. Running the binary
  directly ignores `LSEnvironment`. Neither app has been timed; a first timing round was stopped part-way.
