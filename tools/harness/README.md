# harness: driving and measuring Lichii through its debug server

Tools for running the game unattended in Lichii and A/B-testing settings, builds and patches. What they found is in
[../../research/emulator-options/README.md](../../research/emulator-options/README.md).

| File | What |
| --- | --- |
| `ab.py` | The harness: one run per spec entry (waits for this project's builds, boots, loads the save, settles 3 s, walks with turns at walls, stands, measures), results in `runs/`. Also makes the master config (`--make-master`) and private data roots (`--make-home`) |
| `queue.sh` | `./queue.sh A.json B.json …`: several spec files back to back, each under the emulator lock; `touch PAUSE` makes queues wait (outside the lock) to leave the emulator to other work |
| `config.json` | Defaults: which save to load (`save`: a name in the save library, `save_library`), where the game's saves are (`save_dir`), the session name in the window title |
| `persist.py` | `picture_metrics(png)`, the corruption score every run's end picture gets (`picture` in `result.json`); `python persist.py BURST_DIR…`: in how many frames of a burst each pixel is white |
| `test_app.py` | Test apps, for anything that is not the pinned build: `make NAME [--lichii BINARY] [--moltenvk DYLIB] [--home]` copies the pinned app to `build/test-apps/NAME/` with bundle id `io.github.zortos293.lichii.NAME` (so its own Metal cache) and, with `--home`, its private data root; `ensure NAME` makes a plain copy of the pinned app, and makes it again when the pinned app has changed (the app hand play runs on); `list` shows every Lichii bundle id with a Metal cache (size, last written, stale); `clean NAME` removes an app and its cache |
| `runplan.py` | What a run will do, worked out from its spec: the profiles, each step and where it comes from, and the spec keys the harness knows. `python3 runplan.py` lists the profiles and keys. Launches nothing |
| `metalcache.py` | The Metal shader cache of a Lichii app (macOS keeps one per bundle id) and whether a boot from it is cold; `python3 metalcache.py [APP …]` prints each app's cache size, stamps and what to expect. Takes paths, launches nothing |
| `tests/` | Offline tests of the parts that only read files (the Metal cache, run plans and spec keys, test apps), on made-up folders, on every spec file in the repository and on this machine's recorded runs: `python3 -m unittest discover -s tools/harness/tests` (no emulator, under a second) |
| `dbg.py` | Minimal client for Lichii's debug server (`python3 dbg.py status`, or `from dbg import call`) |
| `uisig.py`, `uiscan.py` | Print the game's UI-manager screens and scene (how the menu states were mapped) |
| [`../diag/`](../diag/README.md) | Readers of a run folder's diagnostic output: `frames.py` (p50 / p90 / p95 / p99 / max per phase from `frames.bin`, bands, segments), `stutter.py` (the stutter trace by phase), `gpu.py` (frame profiler and sync trace), `stats.py` (periodic statistics), `jit.py` (JIT recordings); the catalogue of diagnostic switches and capture specs |
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
4. **Have the save**: in the game, make a save in Kokiri Forest as child Link at the spawn point by his house, and
   add it to the save library as `kokiri-forest` with `python3 ab.py --add-save kokiri-forest SLOT_DIR --spawn
   X,Y,Z` (see "The save").
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

A run loads one save by name from the **save library**, `save_library` in `config.json`
(`~/.local/share/oot26-saves`, outside this repository because saves are game data). Each save is a folder:

```
~/.local/share/oot26-saves/<name>/caption.sav    what the game's Load list shows (map, picture, date)
                                  progress.sav   the save itself
                                  save.json      maps, expect_spawn, source, note
```

Before the boot, the harness deletes every `slot_NN/` of the game's save folder (`save_dir`, in Lichii's NAND:
`~/.local/share/lichii/nand/user/save/…/0400486024DEC000`) and copies that save into `slot_01`; the root's own
`account.sav` and `option.sav` stay. `slot_00` stays empty: leaving an area autosaves there. The Load list then has
one entry, so where the game sorts an imported save does not matter. The menus are read from the game's memory: the
harness presses A on the title screen, opens the Load list, takes its only entry and loads it, and checks that Link
stands within 0.5 m of the save's `expect_spawn` (none when it is `null`). The save folder is left as the run left
it, and the next run replaces it: **a save that matters belongs in the library**, never only in the game's folder
(`--add-save` below copies one in from a slot).

The default is `kokiri-forest`: the Kokiri Forest spawn point by Link's house (x −17.297, y 109.946, z −1.843),
where every number in this repository was measured. `config.json`'s picture checks (`end_white_max`,
`cube_check`) apply to runs of this save only. Set `"save": "<name>"` in a spec entry for another,
and `expect_spawn` there to override the library's.

| Command | What it does |
|---|---|
| `python3 ab.py --list-saves` | The library's saves, with their maps and spawns |
| `python3 ab.py --add-save NAME SLOT_DIR [--spawn X,Y,Z] [--note TEXT] [--force]` | Copies the two files of `SLOT_DIR` (a `slot_NN/` of the game's save folder, or a downloaded save) into the library as `NAME`; the maps are read from its caption. Take the spawn from the first run's `spawn_pos` in `result.json` |
A save from another game version may not load: `option.sav` differs between 1.0 and 1.1.1, and every run here
is 1.1.1 (below). Saves shared by players are collected in
[tustin2121/OoTR-saveTree](https://github.com/tustin2121/OoTR-saveTree) (1.1.1).

**A save that is not in the library.** A `save` name that has no library folder is taken as a map name as the
captions spell it, `Area/Map` or `Map` (for example `GerudoValley_Child`), and the newest save of the game's own
folder with that map is loaded, with `config.json`'s `expect_spawn` unless the spec gives one; `save_index` picks
a Load-list position (0 = newest) instead. Those saves are used as they are. "Newest" is taken from the slots' file
times, while the game sorts the list by the save's date (so the save tree's README says; not checked here), so a
save copied in by hand can be in another place than the harness expects; that is what the library avoids. After a
library run the folder holds only that run's save. `"resave": true` (Plus, R, A, Up, A, B right after the load:
save over the slot that was loaded) only works on these saves, and a library run refuses it.

## The game version

Every run is game 1.1.1 (main build id `E0F3CCFA…`). A `.nup` dump that holds the base game and the update cannot be
booted as 1.0.0: Lichii's loader for that format always applies the newest update package in the file, and
switching `Update` off under `[DisabledAddOns]` changes nothing (tried on 2026-11-19 in a private data root; the
log still named build `E0F3CCFA…`). Testing 1.0.0 would need a base-only dump, or a loader switch that skips the
update package (`FindBestUpdatePackage` in `src/core/loader/nup.cpp`); neither exists here, and the harness has no
option for it.

## Running

```bash
cd tools/harness
./queue.sh specs/batch3.json             # or several files in one call
../verify/verify.py with-lock -- uv run -q --with pillow --with numpy python ab.py specs/smoke.json --only smoke
```

Every run edits Lichii's `qt-config.ini` from the master copy (`qt-config.ini.harness-master`) plus the spec's `cfg`
and puts the master back afterwards. A missing master stops the batch with the `--make-master` command to run.

Each run has a profile (`"profile"` in its spec entry), which decides its steps:

| Profile | Steps | For |
| --- | --- | --- |
| `measure` (the default) | boot, load the save, settle, walk, stand, score the end picture | frame times, A/B comparisons |
| `load` | boot, load the save, settle, score one picture (`run-end.png`), stop | checking a build, a save or the harness itself: no frame times |
| `boot` | boot to the title screen, stop; the save folder is left as it is | warming the shader caches (`--warm`), boot times |

`python3 ab.py --plan SPEC.json` prints each run's steps in order without launching anything, and every batch
prints the same line per run before its first boot. A step that `config.json` adds says so: for runs of its save it
adds the clipped-white limit, and the cube check when that is turned on there (see `cube_check` below). A spec with a key the harness does not
know, or a key its profile has no step for, is refused before anything boots.

A spec is a JSON list of runs: `label`, `desc`, `cfg` (config keys), `env` (`{rd}` = the run folder), `app`
(default `${REPO}/build/app/lichii.app`; `${REPO}` stands for this repository's folder in any spec), `args`,
`repeat`, `phase_frames`, `variants`, `server_calls`, `lock_minutes` (the lock's lease for this run: minutes without
a reported step after which another taker may evict it; default 30, 5 to 90; see [../verify/README.md](../verify/README.md), "The lock"), `settle_s` (default 3: seconds with no pipeline build before
measuring), `walk` (`bounce`, the default: run in 30-frame chunks and turn round when stuck (two quarter turns: left
stick right, then a right-stick click to put the camera behind Link; then forward again); `route`: the old fixed
route), `stand_first` (add a standing phase before the walk), `cold_metal_cache` (boot from an empty Metal cache, the
run's app's own one held aside and restored), `save` / `expect_spawn` / `save_index` (another save, see "The save"), `home` (a private
data root, see below), `jsdbg` (`attach` / `arm`, see below), `flicker`, `capture`, `profile` (above), and these, each off unless set:

- `stand_frames`: length of the stand after the walk (default `phase_frames`).
- `walk: "waypoints"` with `waypoints` (a list of `[x, z]` points in the game's coordinates): Link is steered to each
  point in turn and the walk phase is that route, however many frames it takes. The left stick is relative to the
  camera, which is not read, so the stick angle is corrected by feedback: after every 10 frames the direction he
  actually moved is compared with the bearing of the next point and the stick is turned by the difference; which
  way a stick turn moves him is measured at the start. A point counts as reached within `waypoint_radius_m`
  (default 1.5); a leg is given up after `waypoint_frames` (default 900) or six blocked attempts, and the run's line
  says which points were missed. `waypoint_start` is a point he is brought to before the measured phase begins
  (the debug server cannot write memory, so this stands in for a teleport); `run-walkstart.png` is taken there.
  `result.json` gets the path and each leg's frames under `walk_call`. Positions come from the game's placement
  data. A route used for the Kokiri Forest save: start `[10.0, -1.0]` (in the stream beside the spawn), then
  `[[-29.5, 5.9], [10.0, -1.0]]` (Saria's placement and back): about 1,550 frames, crossing the stream bed twice.
- `leash_m`: in a bounce walk, also turn round when Link is that far from where the walk began and still moving
  away, so a long walk stays in the area instead of leaving the map (which loads another one and autosaves).
- `at_end`: steps run once Link has stopped where the walk ended (`../speckcheck/speckhunt.py`): window-capture
  bursts scored by `whitecount.py` with a sheet and a GIF, debug-server calls, shader-reject groups. `flicker` and
  `capture` run at the spawn instead. `../speckcheck/speck_report.py RUNS_DIR` prints one verdict line per run.
- `walk_shots`: a window capture after each walk chunk, with a sheet, a GIF and the white share per frame
  (`walk_white_pct`). It changes the walk (on 2026-11-17 Link ended 9 m short of the cave wall with it), so never
  combine it with `at_end`.
- `end_white_max`: a limit, in percent, on clipped-white pixels in the end picture, below `picture_metrics`' own 15 %:
  the picture counts as corrupted above it. `config.json` sets 1.0 for runs of the default save (a clean Kokiri
  Forest scene scores 0.0; the canopy shards of KNOWN-ISSUES KI-29 score 2.6-2.8); a run of another save has no
  such limit unless its spec gives one. The end picture shows one view: corruption that needs a particular object on screen is
  missed when Link ends facing away from it (one of the KI-29 boots ended facing a rock wall and scored 0.0).
  To catch that, run `tools/speckcheck/shotwatch.py` beside the batch; its captures cost about 50 ms each inside
  Lichii (two a second raised walk p95 by about 3 ms and p99 by 5-13 ms), so not beside a timing run.
- `cube_check`: N frame captures in a row after the end picture, read for the 128x128 lighting cube the game
  redraws one face a frame; a value over 50 in it marks the run corrupt (`cube_max` in `picture`). It catches the
  corrupted-lighting boots of [KNOWN-ISSUES](../../KNOWN-ISSUES.md) KI-29 whichever way Link faces: the end
  picture alone flags such a boot only when it shows the big tree at the spawn (two of the four bad boots seen
  scored 0.0 % white). **Off by default** (`"cube_check": 0` in `config.json`): it adds about a minute and 1 GB of
  captures to every run, and the fault was seen in 4 of about 120 boots, all on 2026-11-19. Turn it on again:
  - for every run of the default save, with `"cube_check": 8` in `config.json`, when a corrupted-lighting boot is
    seen again (white or multicoloured shards in the canopy, grass lit bright yellow, or an end picture over the
    clipped-white limit), and for as long as that fault is being chased;
  - for one batch, with `"cube_check": 8` in its spec entries, when a comparison must not include a corrupt boot
    (validating a change to the pinned build) or when lighting or texture corruption is what is being debugged.
  When the run scores clean, its cube-check captures (about 1 GB a run) are deleted after scoring; `result.json`
  keeps the verdict, the largest value (`cube_check.max`) and `captures_deleted_mib`.
- `keep_cube_captures`: keep the cube check's captures of a clean run.
- `on_corrupt`: evidence collected only when the run's end picture scores as corrupted, while the game is still
  up. Off unless the spec sets it: `true` runs `config.json`'s steps (a GPU trace, four frame captures with sampled
  textures and a bug bundle: about 2.5 minutes a run and about 1 GB a capture; twelve took 21 GB), a list runs
  those steps (the same kinds as `at_end`'s). Every run's `result.json` gets `picture` (`clipped_pct`, `vivid_pct`,
  `corrupt`: clipped over 15 % or vivid over 0.15 %, from `persist.picture_metrics` on `run-stand2.png`); a corrupt
  one is also printed as `CORRUPT PICTURE`.
- `build_wait`: `false` starts even while one of this project's variant builds is compiling (for runs judged by
  picture or log; frame times are then skewed).
- `hold_file` / `hold_max_s`: right after the load, write main's address and Link's object to that file and keep
  the game open for manual debug-server calls until the file is removed (at most `hold_max_s`, default 900 s). The
  file also names the Lichii (`lichii_pid`) and the attempt (`"1/1 retry"` after a crash): a client that sees either
  change is driving a new game. If Lichii dies while held, `<hold_file>.died` appears at once, with the pid, how long
  it was held and the newest Lichii crash report.
- `after_hold`: `"stop"` ends the run when the hold does (outcome `completed (held, then stopped)`): no settle, walk,
  stand or picture scoring, which would use a Link that a warp may have replaced. For manual sessions.
- `resave`: save again right after the load, for a save that is not in the library ("The save").

A bounce walk that stands still for three chunks in a row (Link in an NPC dialog, or stuck where a turn does not
free him) is marked: `walk_stalled` in `result.json` and in the run's line, and `WALK STALLED` printed, because its
frame times from there are not a walk. A run that ends early with the guest's own crash in the log ("Unhandled guest
exception" from the Hypervisor backend, "Cannot execute instruction at unmapped address" from the JIT) gets the
outcome `error: guest crashed` and is retried once.

Each run folder holds `result.json` (frame statistics per phase, boot and load times, build counts, positions, the
picture score), the per-present clock `frames.bin`, `eden_log.txt`, screenshots, and on failure a stack sample or
screenshot.

### Cold boots

A boot is cold when Metal has to compile the shaders again instead of reading them from its cache: minutes instead
of seconds, and stutter while the rest compile. Its boot, load and frame-time numbers are not a warm run's, so each
run says which it was. `result.json` gets `cold` (true or false), `cold_reasons`, and `metal_cache`: the macOS
build, the cache of the app that booted before and after the run (bundle id, folder, size, stamps), and how many
builds Metal's compiler did for this Lichii during boot and load (`compile_requests_boot_load`) and over the whole
run (`compile_requests_run`), counted from the system log. The run's line prints `COLD` with the reasons, and when
the cold boot is known before it starts the window title says so from the first second. The reasons:

- `empty Metal cache`: the app never ran, or the spec set `cold_metal_cache`. A new test app's first boot is always
  this: its bundle id has no cache yet, and a copy of the pinned app's cache does not help (Metal compiled 2,719
  shaders with the copy against 2,724 without, run ab-20261127-194647, local run data, not tracked). Its second
  boot is warm.
- `Metal cache reset (macOS update)`: a macOS update changes the stamp in the cache's `.list` files and Metal drops
  every entry written under the old one. The harness sees it beforehand when another Lichii app's cache, written
  later, carries a different stamp, and afterwards when the stamp changed during the run.
- `N shaders compiled during boot and load`: more than 500 compiler builds, whatever the cause.

`python3 metalcache.py [APP …]` prints the same check for an app without booting it.

### Judging a change by frame times

`python3 accept.py RUNS_DIR CONTROL_PREFIX CHANGE_PREFIX [--phase walk]` applies the pinned build's frame-time rule
to paired runs (`route-off-1` with `route-on-1`, and so on; run the pairs alternating, on a fixed route). For p50,
p95 and p99 of the phase, a pair's ratio is (60 − fps of the control) ÷ (60 − fps of the change): how much of the
shortfall from 60 fps the change closes. The change is accepted when the one-sided 90 % lower confidence bound of
that ratio (Student t on the pairs' log ratios) is above 1.1 for at least one of the three, the mean ratio of none
of the three is below 1.0, and no picture scored as corrupt. A percentile whose control is within 2 fps of 60 is at
the target and is not scored, which is why the stand in Kokiri Forest cannot be used. Three pairs settle a large
effect; add pairs only when a mean is above 1.1 and its bound is not.

A boot that follows an interrupted one is the opposite trap: Lichii then builds none of the pipeline file's
pipelines (its guard against a pipeline that crashes the boot; the log says "building none at boot this time"). It
reaches the title in seconds and compiles nothing, so it looks warm, and the boot after it builds everything.
`result.json` records it as `pipeline_boot` (`in_file`, `built`, `skipped`) and the run's line prints
`PIPELINES NOT BUILT`; `--warm` boots such a root a second time.

After a macOS update, or with a new build, have the cold boot outside any measurement:
`python3 ab.py --warm [--app APP] [HOME …]` boots each data root once (none named: the real folders) with profile
`boot`, under the emulator lock, which it takes itself. `./build.sh install` runs it after installing.

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
0.0.14 since 2026-11-26, built from tag `v0.0.14`; its files are in Lichii's `load/0400486024DEC000/sloperinaGZ` and
`sdmc/sloperinaGZ`, installed as its INSTALLATION.md says, with the build line in `sloperinaGZ/subsdk9-build.txt`).
The builds it replaced (2026-11-19, and 0.0.13) are kept in `~/.local/share/oot26-backups/` (not under `load/`,
where Lichii would take them for mods). The smoke test with 0.0.14 (run ab-20261126-112724) walked at 18.9 ms and
stood at 17.5 ms; with 0.0.13 (run ab-20261126-080917) it was 18.6 and 16.9 ms, and the 2026-11-19 runs with 0.0.9
gave the same. sloperinaGZ reads the owner's `settings.ini` (version 1) and updates it in memory at
each boot; the harness puts the file back after each run as before. The harness reads game state from memory and does not need it, except for `variants` (its
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
