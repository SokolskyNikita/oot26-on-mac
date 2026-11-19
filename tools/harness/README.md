# harness: driving and measuring Lichii through its debug server

Tools for running the game unattended in Lichii and A/B-testing settings, builds and patches. What they found is in
[../../research/emulator-options/README.md](../../research/emulator-options/README.md).

| File | What |
| --- | --- |
| `ab.py` | The harness: one run per spec entry (waits for this project's builds, boots, loads the save, settles 3 s, walks with turns at walls, stands, measures), results in `runs/`. Also makes the master config (`--make-master`) and private data roots (`--make-home`) |
| `queue.sh` | `./queue.sh A.json B.json …`: several spec files back to back, each under the emulator lock; `touch PAUSE` makes queues wait (outside the lock) to leave the emulator to other work |
| `config.json` | Defaults: which save to load (`save` by map name, or `save_index`), where Link must stand after it, where the saves are, the session name in the window title |
| `persist.py` | `picture_metrics(png)`, the corruption score every run's end picture gets (`picture` in `result.json`); `python persist.py BURST_DIR…`: in how many frames of a burst each pixel is white |
| `dbg.py` | Minimal client for Lichii's debug server (`python3 dbg.py status`, or `from dbg import call`) |
| `uisig.py`, `uiscan.py` | Print the game's UI-manager screens and scene (how the menu states were mapped) |
| `jitlog.py` | `python jitlog.py RUN_DIR`: summary of a per-compile JIT log (`jit.bin`) from a build with `patches/experiments/dynarmic-jit-log-2026-11-17.patch` run with `EDEN_NX2_JIT_LOG`: phase split, per core, repeats across cores, per-second timeline, modules and pages |
| `stuttercause.py` | `python stuttercause.py RUN_DIR…`: the stutter trace's slow frames per harness phase, by time (JIT, pipeline builds, GPU-side waits) |
| `stutterjit.py` | Older per-phase view of the stutter trace by frame number (game frames, not presents: use `stuttercause.py`) |
| `p95.py` | `python p95.py RUN_DIR…`: p50 / p90 / p95 / p99 / max per phase from `frames.bin`, for runs made before p95 was recorded |
| `../speckcheck/` | Speck tools (screenshot bursts scored for white specks, GPU trace replay). `ab.py` imports `speckhunt` and `whitecount` from there for `at_end`, `walk_shots` and `on_corrupt` |
| `session.sh` | One interactive Lichii session with the debug server on, under the lock; `touch STOP` ends it |
| `specs/` | Run specs, all against the pinned build unless they say otherwise: `smoke`, `pinned-validate` (three measured runs), the settings and switch batches `batch1`–`batch5` and `tooling`, `fastmath2`, `debugcost2`, `fullscreen`, `bilinear`, `fsr`, `async-skip-cold` (Bounded against Wait from an empty Metal cache), `hitch-rate` (five walks), `gerudo-and-long` (a second area and one-minute phases), `cold-boot`. Specs of past batches that compared test apps are not kept: each run's `result.json` holds the spec it ran (`spec` key), and the write-ups give the labels |
| `build-variants/` | `prebuild-variants.sh` (LTO, PGO, upstream-LLVM builds), `pgo-pipeline.sh` and `build-mvk-par.sh` (the parallel-shader-compile MoltenVK variants). They expect the local build trees they were written for, which are not part of this repository |
| [`../../patches/experiments/`](../../patches/) | The changes these runs tested and did not adopt: the JIT flush, the Hypervisor experiments, the per-compile JIT log, the MoltenVK pipeline-cache progress log and the parallel-compile variants (`moltenvk-<variant>-vs-path60-*.patch`, against the MoltenVK tree of the path-to-60fps work) |
| `shader-refs/mipflow.json` | The list of fragment programs with per-pixel conditional samples, from the shader analysis in [`wip/shader-metal-analysis`](../../wip/shader-metal-analysis/README.md) |

## Setting up on a new machine

Prerequisites: an Apple silicon Mac with the Command Line Tools (`clang`, `lldb` only for debugger runs), the
Homebrew packages of [../../README.md](../../README.md) "Building it", [`uv`](https://docs.astral.sh/uv/) (the
harness runs under `uv run` with numpy and Pillow), and your own dump of the game (title `0400486024DEC000`,
v1.1.1) as a `.nup` file: set `OOT26_DUMP` to it, or put it in `dump/` in this repository or beside it.

One-time steps, from the repository root:

1. **Build the app**: `./build.sh` (makes `build/app/lichii.app`, the pinned build; specs name it
   `${REPO}/build/app/lichii.app`, and it is also the default `app`).
2. **Build the frame hook**: `cd tools/verify && ./verify.py build-hook` (writes `build/libverifyhook.dylib`;
   `ab.py` also builds it when it is missing or older than `hook.m`).
3. **Run the game once in Lichii**, by hand: open the app, add the folder with your dump, boot the game, and quit
   Lichii. This writes `~/.config/lichii/qt-config.ini`. In Lichii's settings, set the values in
   [`config/settings.txt`](../../config/settings.txt) (or, with Lichii closed, `python3 config/apply-settings.py`),
   and switch off the game's built-in "Max Resolution", "FPS Unlock" and "Dynamic FPS" add-ons
   ([`config/README.md`](../../config/README.md)). Player 1 must be connected (`player_0_connected=true`, Lichii's
   default): the debug server's input goes to player 1, or to the handheld controller when player 1 is off. No
   controller binding is needed for the harness (see "Input" below).
4. **Have the save**: in the game, make a save in Kokiri Forest as child Link at the spawn point the default
   `config.json` expects (see "The save").
5. **Make the master config**, with Lichii closed: `cd tools/harness && python3 ab.py --make-master`. It checks
   `qt-config.ini` against `config/settings.txt` (through `config/apply-settings.py --check`), refuses if any
   setting differs, and copies it to `~/.config/lichii/qt-config.ini.harness-master`. The harness puts this copy
   back before and after every run. To change the settings later, edit them with Lichii closed and run
   `python3 ab.py --make-master --force`.

Then the smoke test (about 2 minutes on a warm shader cache; the first boot after a new MoltenVK library compiles
every shader, about 100 s more):

```bash
cd tools/harness
./queue.sh specs/smoke.json
```

It boots the pinned app twice (`smoke-warmup`, then `smoke`) and prints one line per run with the boot and load
times and the walk and stand frame times (p50 / p90 / p95 / p99 / max, ms). Look at the screenshot
`runs/ab-*/smoke/run-stand2.png`: a dark forest with Link in it. The first boot on a cold shader cache fails the
hang check only if nothing at all moves for 3 minutes; a slow boot is not a hang (`config/README.md`, "The shader
cache and MoltenVK").

`python3 ab.py --print-paths [SPEC.json]` prints every file a run would read and write, without launching anything.

## Input

`ab.py` drives the game only through Lichii's debug server (`EDEN_NX2_DEBUG_SERVER`, set by the harness): menu
presses and the walk are `input_sequence` calls, which add their buttons and sticks to player 1's (or the
handheld controller's) state by presented frame (`src/core/debugger/nx2_debug_tools.cpp`, `RunInput`, and
`EmulatedController::GetNpadButtons`). No controller server, binding or window focus is needed, and none is
started. Runs with `"server": false` are refused.

`../verify/verify.py run`, the older single-run checker, is the one tool that presses buttons through a virtual
controller: it starts [`../pad/dsu_server.py`](../pad/README.md) itself when nothing answers on its control port
and stops it afterwards. That needs player 1 bound to the DSU controller in Lichii (see `../pad/README.md`).

## The save

The default `config.json` loads the newest save whose caption (`caption.sav`) names the map `KokiriForest_Child`
and checks that Link then stands at `expect_spawn` (x −17.297, y 109.946, z −1.843, within 0.5 m: the Kokiri
Forest spawn point by Link's house, where every number in this repository was measured). The saves are found in
`save_dir`, the game's save folder in Lichii's NAND (`~/.local/share/lichii/nand/user/save/…/0400486024DEC000`,
one `slot_NN/` per save; the profile folder name differs per machine, so set yours). The menus are read from the
game's memory: the harness presses A on the title screen, opens the Load list, moves the cursor to that save and
loads it.

To use another save, set in `config.json` (all runs) or in a spec entry (one run):

- `save`: a map name as the captions spell it, `Area/Map` or `Map` (for example `GerudoValley_Child`); the error
  message when none matches lists the map of every save there.
- `expect_spawn`: where Link stands after loading it (`spawn_pos` in any run's `result.json`), or `null` to skip
  the check.
- `save_index`: a Load-list position (0 = newest) instead of looking up `save` by name.

**Keep the forest save on top.** The game's Load list is newest first, and every default run loads
`KokiriForest_Child`. After a session that saved somewhere else, load the forest save and save again at once, so it
does not sink down the list. A spec with `"resave": true` does it right after the load: Plus (pause menu), R
(System tab, Save is its first entry), A (Save dialog, Cancel selected), Up, A (saves over the slot that was
loaded), B. The run fails if the slot's `caption.sav` did not change. Leaving an area autosaves into slot_00, which
also pushes the forest save down.

## Running

```bash
cd tools/harness
./queue.sh specs/batch3.json             # or several files in one call
../verify/verify.py with-lock -- uv run -q --with pillow --with numpy python ab.py specs/smoke.json --only smoke
```

Every run edits Lichii's `qt-config.ini` from the master copy (`qt-config.ini.harness-master`) plus the spec's `cfg`
and puts the master back afterwards. A missing master stops the batch with the `--make-master` command to run.

A spec is a JSON list of runs: `label`, `desc`, `cfg` (config keys), `env` (`{rd}` = the run folder), `app`
(default `${REPO}/build/app/lichii.app`; `${REPO}` stands for this repository's folder in any spec), `args`,
`repeat`, `phase_frames`, `variants`, `server_calls`, `lock_minutes` (the lock's lease for this run: minutes without
a reported step after which another taker may evict it; default 30, 5 to 90; see [../verify/README.md](../verify/README.md), "The lock"), `settle_s` (default 3: seconds with no pipeline build before
measuring), `walk` (`bounce`, the default: run in 30-frame chunks and turn round when stuck (two quarter turns: left
stick right, then a right-stick click to put the camera behind Link; then forward again); `route`: the old fixed
route), `stand_first` (add a standing phase before the walk), `cold_metal_cache` (boot from an empty Metal cache, the
real one held aside and restored), `save` / `expect_spawn` / `save_index` (another save, see above), `home` (a private
data root, see below), `jsdbg` (`attach` / `arm`, see below), `flicker`, `capture`, and these, each off unless set:

- `stand_frames`: length of the stand after the walk (default `phase_frames`).
- `leash_m`: in a bounce walk, also turn round when Link is that far from where the walk began and still moving
  away, so a long walk stays in the area instead of leaving the map (which loads another one and autosaves).
- `at_end`: steps run once Link has stopped where the walk ended (`../speckcheck/speckhunt.py`): window-capture
  bursts scored by `whitecount.py` with a sheet and a GIF, debug-server calls, shader-reject groups. `flicker` and
  `capture` run at the spawn instead. `../speckcheck/speck_report.py RUNS_DIR` prints one verdict line per run.
- `walk_shots`: a window capture after each walk chunk, with a sheet, a GIF and the white share per frame
  (`walk_white_pct`). It changes the walk (on 2026-11-17 Link ended 9 m short of the cave wall with it), so never
  combine it with `at_end`.
- `on_corrupt`: steps like `at_end`'s, run only when the run's end picture scores as corrupted, while the game is
  still up (a GPU trace, a frame capture). Every run's `result.json` gets `picture` (`clipped_pct`, `vivid_pct`,
  `corrupt`: clipped over 15 % or vivid over 0.15 %, from `persist.picture_metrics` on `run-stand2.png`); a corrupt
  one is also printed as `CORRUPT PICTURE`.
- `build_wait`: `false` starts even while one of this project's variant builds is compiling (for runs judged by
  picture or log; frame times are then skewed).
- `hold_file` / `hold_max_s`: right after the load, write main's address and Link's object to that file and keep
  the game open for manual debug-server calls until the file is removed (at most `hold_max_s`, default 900 s).
- `resave`: save again right after the load (above).

Each run folder holds `result.json` (frame statistics per phase, boot and load times, build counts, positions, the
picture score), the per-present clock `frames.bin`, `eden_log.txt`, screenshots, and on failure a stack sample or
screenshot.

### A private data root

A run can use its own copy of Lichii's folders, so a test build never touches the real config, saves, logs or
shader caches: `"home": "DIR"` in a spec entry, or `OOT26_LICHII_HOME=DIR` for every run without one. Lichii is
then started with `XDG_CONFIG_HOME=DIR/config`, `XDG_DATA_HOME=DIR/share` and `XDG_CACHE_HOME=DIR/cache`; it appends
`lichii` to each (`src/common/fs/path_util.cpp`), so its folders are `DIR/config/lichii`, `DIR/share/lichii` and
`DIR/cache/lichii`. Everything the harness reads or writes moves with it: the config it rewrites and restores, the
master (`DIR/config/lichii/qt-config.ini.harness-master`), the log, and `save_dir` (resolved under
`DIR/share/lichii`). A run refuses to start when the private config or master still names a path in the real
folders, or when its working directory holds a `user/` folder (Lichii's portable mode, which would win).

Make one from the real folders, with Lichii closed:

```bash
python3 ab.py --make-home DIR                      # shader caches left empty: the first boot takes about 5 minutes
python3 ab.py --make-home DIR --with-shader-cache  # also the game's shader cache folder, as APFS clones (cp -c)
```

It copies `qt-config.ini` and `custom/`, the NAND (`nand/`: saves and system files), the practice tool and its data
(`load/0400486024DEC000/`, `sdmc/`), and `keys/`; the master is the real harness master when there is one (else it is
made from the copied config, after the settings check). Every setting pointing into the real folders
(`[Data%20Storage]` `nand_directory`, `sdmc_directory`, `load_directory`, `dump_directory`, `tas_directory`, the
screenshot folder) is rewritten to the same place in `DIR` and printed. The real folders are only read.

Not moved by a private root: the emulator lock (`~/.local/share/lichii/verify.lock`, shared on purpose: one emulator
at a time), and macOS's Metal shader cache (`$(getconf DARWIN_USER_CACHE_DIR)/io.github.zortos293.lichii/`, which
belongs to the app's bundle identifier, not to Lichii's folders).

### Debugger runs (`jsdbg`)

`"jsdbg": "attach"` or `"arm"` starts the lldb logger `jsdbg.py` once Lichii waits for a debugger (with
`use_gdbstub=true` in `cfg`). The logger is part of the glitch-research repository this one grew out of, not of this
one, and no measurement needs it: set `OOT26_JSDBG_DIR` to its folder (the default is `emulator/debug` beside this
repository). A spec that asks for it when it is not there stops before the first boot.

## The practice tool

The game in this setup has the practice tool sloperinaGZ installed ([PracticeROM/sloperina](https://github.com/PracticeROM/sloperina),
0.0.9; its files are in Lichii's `load/0400486024DEC000/sloperinaGZ` and `sdmc/sloperinaGZ`, installed as its
INSTALLATION.md says). The harness reads game state from memory and does not need it, except for `variants` (its
position save and restore, R + D-pad up / down) and `flicker` (which hides its watch panel). `../verify/verify.py
run` needs it: it finds the spawn point from the tool's watch panel. The numbers in this repository were measured
with it installed.

For each run the harness switches off the tool's binds that collide with buttons it presses, and puts the tool's
`settings.ini` back afterwards (the owner's file is kept beside it as `settings.ini.harness-saved` during the run).
One bind collides: since 0.0.9 the right-stick click is the tool's "ragdoll" command, which knocks Link over, and
the harness clicks the right stick to put the camera behind Link whenever it turns him at a wall. Runs made with
0.0.9 before this was handled (2026-11-19, run ab-20261119-053233) have Link lying on the ground for part of the
walk and are not valid; walks with no turn are unaffected.

## Rules the harness follows

From what went wrong: game state comes from memory, never from screenshots; `main`'s address is read from each
boot's log (ASLR); never queue specs as separate waiters on "no queue.sh running" (they match their own command
lines); a debugger attaches only once the guest is held.
