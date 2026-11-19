# verify: check a rendering change in Lichii

`verify.py` boots any Lichii app copy, loads the top save in Kokiri Forest, stands, walks a fixed route twice,
and saves everything about the run in one directory: frame times, Metal/MoltenVK errors and screenshots. `compare`
puts two runs side by side and exits nonzero when the candidate is worse. It replaces the manual parts of
`measure.sh`, an older measurement script of the separate glitch-research repository this one grew out of.

Needs: `uv` (it runs the script with numpy and Pillow), the Command Line Tools (`clang` builds the hook on first
use, or `./verify.py build-hook`), Lichii's player 1 bound to the virtual controller
[`../pad/dsu_server.py`](../pad/README.md) (`run` starts that server itself when nothing answers on its control port
and stops it afterwards), and the practice tool sloperinaGZ installed in Lichii (its watch panel tells the spawn
point; see [../harness/README.md](../harness/README.md), "The practice tool"). The harness only uses the lock and the
hook from here.

## Usage

```bash
cd tools/verify
./verify.py run ../../build/app/lichii.app pinned-ref              # reference
./verify.py run /path/to/other/lichii.app my-change MVK_CONFIG_FOO=1  # candidate, optional ENV=VALUE pairs
./verify.py compare runs/stock228-ref-<stamp> runs/my-change-<stamp>
./verify.py analyze runs/<run>          # redo result.json from a run's files (after changing the error rules)
./verify.py lock-status
./verify.py build-hook                  # build/libverifyhook.dylib (also built by run and by the harness)
./verify.py with-lock -- ./measure.sh LABEL   # run anything else that uses the emulator under the same lock
```

A run takes 5 to 8 minutes (boot, shader cache load, menus, about 3,000 game frames of route). Run it in the
background. To stop one early, send SIGTERM to the Python process (`lock-status` shows its pid, not uv's): it
kills its own Lichii and releases the lock.

`compare` exit codes: 0 not worse, 1 worse, 2 not worse but there are error lines of a kind the reference does not
have (check them by hand).

## What a run directory holds

| File | What |
| --- | --- |
| `result.json` | the numbers: frame stats per phase, Lichii's 600-present windows, error counts by category with shader ids, unrecognised error lines, shots, config and shader cache changes, load average |
| `meta.json` | app, env, hashes of the app's `lichii` and `libMoltenVK.dylib`, marks (frame number and log time of each phase), config and shader cache hashes before and after |
| `frames.bin` | one uint64 per presented frame: nanoseconds of `CLOCK_UPTIME_RAW` |
| `stderr.log` | Lichii's stdout and stderr, with `MVK_CONFIG_LOG_LEVEL=2` (MoltenVK errors) |
| `eden_log.txt` | copy of `~/.local/share/lichii/log/eden_log.txt` at the end of the run |
| `shots/*.png` | window captures at the fixed points |
| `diff/*.png` | written by `compare`: reference and candidate side by side, changed tiles boxed in red |

## The lock

Only one emulator may run at a time: two spoil every measurement, and there is one config and one shader cache.

- The lock is the directory `~/.local/share/lichii/verify.lock`. `mkdir` either creates it (you own it) or fails
  (someone else does), so taking it is atomic. `owner.json` inside holds the owner's pid, label, app, start time
  and the pid of the Lichii it started.
- After taking it, the tool also checks for any running process named `lichii`. If one is running, the tool did not
  start it: it releases the lock and waits. It never kills a Lichii it did not start.
- Waiting is bounded: `--lock-wait` seconds (default 1800), checking every 10 s, then it gives up with the reason.
- Stale locks: if the owner's pid is dead, or the directory has had no `owner.json` for 60 s, it is removed.
- Released on every exit, including SIGTERM and Ctrl-C (it kills its Lichii first). Release removes the
  directory only if `owner.json` names this process.
- `measure.sh` does not know about the lock, and it starts with `pkill -9 -f '[l]ichii.app/Contents/MacOS'`,
  which kills any Lichii, including one in a verify run. Run it as `./verify.py with-lock -- ./measure.sh LABEL`.

## How it works

### The hook (`hook.m`, built to `build/libverifyhook.dylib`)

Loaded into Lichii with `DYLD_INSERT_LIBRARIES`. This works because Lichii copies are ad-hoc signed with no
hardened runtime. The hook removes itself from the environment, so Lichii's child processes do not load it.

- **Frame clock.** It swizzles `-[CAMetalLayer nextDrawable]`: MoltenVK takes one drawable per presented frame.
  Each call appends a timestamp to `frames.bin`. The counts agree with Lichii's own `last 600 presents` averages
  (stock, standing: hook 47.72 ms, Lichii 47.62 ms).
- **Screenshots, without the screen or focus.** A process may capture its own windows without the Screen Recording
  permission. So the hook captures Lichii's main window from inside, with `CGWindowListCreateImage` on its own
  window id. This works while the window is behind other windows; a minimised window or one on another Space was
  not tried. `screencapture -l <id>` from a shell fails (`could not create image from window`) when the shell's
  app has no Screen Recording permission. The window is captured at 1x (1280 points wide).
- Control is UDP on `127.0.0.1:26799`: `count` returns the frame count, `shot <path>` writes a PNG.

### Solving the positioning problem: inputs by game frame

The game steps a fixed 1/60 s per rendered frame, so a stick held for 4 s of wall-clock time moves Link further on
a faster build. `verify.py` schedules every stick change and screenshot by the hook's frame count instead
(`Driver.until`). The route is `WALK` in `verify.py`: measure.sh's walk with its seconds turned into frames at
~30 fps, stick movements of 45 to 120 frames, and a screenshot after each camera turn with the sticks centred for
15 frames.

- **Start point.** After the menus, the tool waits until the sloperinaGZ watches panel shows the spawn position
  (x −17.30, y 109.95, z −1.84). It matches the panel's x/y/z digits against `spawn-watch.png`: a mean difference
  of 0.0 to 0.4 at spawn, 18.4 on the menus, 12.2 at another spot; the threshold is 4. Standing starts 120 frames
  after that, and the spawn shots are at +90 and +990 frames into standing.
- **Menus** use measure.sh's timing (14 s, then A every ~3 s), but each press is held for 4 game frames. A 120 ms
  wall-clock tap can fall between two slow frames and be lost; that left one measure.sh-style run on the Load
  menu. If Link is not at spawn 60 s after the last press, and the screen is not black (a load in progress), the
  tool presses A again, at most 3 times.
- **How repeatable.** The `pos` column of `compare` diffs the watches panel's x/y/z numbers between the two shots.
  Stock vs stock (two runs), it was 0.00 at both spawn shots and 0.8 to 5.5 at the six route shots. That is a
  last-digit difference: the same spot within about 0.05 units, compared with 12 for a different spot. Inputs
  travel through the DSU server (250 Hz) and Lichii's input polling, so a stick change can land one frame late.
- The game area is found in each capture by the strongest pair of horizontal edges one 16:9 height apart. The
  title bar is 28 pt on build 228 and 32 pt on the nx2 builds.

### Frame times

Per phase (`standing` 1,050 frames, `walk1` and `walk2` 944 each, `walks` both): mean, median, p95, p99, max and
frames over 100 ms, from `frames.bin`. The tool also lists Lichii's own `last 600 presents` lines, as measure.sh
does, each tagged with the phase it ended in. Because phases are measured in frames, both builds render the same
game content in each phase.

Noise: builds of Lichii and MoltenVK ran on the same machine. During the demonstration runs the load average was 14 to
54 (`result.json` → `load_average`). Two stock runs agreed on the walk1 median (41.4 vs 42.9 ms) but not on standing or
walk2, where shader compiles after a shader cache switch land. Each run records the 1-minute load average at start and
end in `result.json`, prints a warning above 8, and `run --max-load N` refuses to start above N; `compare` warns when
either run was above 8. `compare` counts a median more than 10% slower (`--slower`) as worse. Treat smaller differences
as noise unless they repeat.

### Errors

The scanner reads `stderr.log` (each `[mvk-error]` line with its continuation lines is one event) and `eden_log.txt`
(`<Error>`/`<Critical>` lines plus the warnings the rules know). Categories:

| Category | Matches | Known cause |
| --- | --- | --- |
| `threadgroup_memory` | `Threadgroup memory size (N) exceeds the maximum threadgroup memory` | native mesh pipelines over 32,768 bytes; foliage missing |
| `stage_resource_limit` | `wants to bind buffer/sampler/texture N which goes above the limit` | MoltenVK main's `maxPushDescriptors`; canopy missing, sky holes |
| `sampler_array_limit` | `Texture arrays exceed descriptor limits` | Lichii build 228 refusing pipelines over 16 samplers (fixed later, Lichii#1862) |
| `compute_buffer_index` | `'buffer' attribute parameter is out of bounds` | 5 compute shaders on MoltenVK main |
| `device_lost_or_crash` | `DEVICE_LOST`, `Cannot execute instruction`, `FastmemCallback`, `Failed to present` | |
| `draw_skipped` | `Draw skipped` | draws whose pipeline was not ready; varies with timing |
| `pipeline_failed` | other failed pipelines: `pipeline build failed`, `could not be compiled into pipeline`, `Shader library compile failed`, `VK_ERROR_INITIALIZATION_FAILED` | |

An event goes to the first category that matches. Shader ids are listed where the line has them: 16-hex-digit
pipeline hashes, `shader=`/`pipeline=` values, and the guest `vs=`/`ps=` addresses in `Draw skipped`. MoltenVK's
own messages carry none. Every other error line is listed under `unrecognised_errors`, with numbers folded so that
repeats merge. `compare` lists kinds that the reference does not have, and exits 2 if those are the only finding.
Add a rule to `ERROR_RULES` once a new kind is understood.

`compare` counts the candidate as worse when any category's count goes up. For `draw_skipped`, it has to go above
1.5 × the reference count + 10.

### Picture check

Each shot's game area (1280×720) is cut into 40×40 px tiles (32×18), and each tile's mean colour is compared.
A tile counts as changed when its mean colour moves by more than **20** (0–255, largest channel). A shot **fails
when more than 10%** of tiles changed. The tiles under the watches panel are left out (they hold the position
check instead).

Why tile means: a per-pixel diff flags every edge when the camera is a fraction of a pixel off, and leaves sway.
A tile's average is stable under both. A missing canopy, missing grass or a hole in the sky replaces what covers
the tile, so its average moves far.

How the thresholds were picked: stock 228 against stock 228, two runs, eight shots. At 20, 0.8% to 4.5% of tiles
changed (the most was a patch of ground lit differently by moving light shafts), so 10% leaves about 2× margin.
For the known-bad result, see "Demonstration" below.

## Demonstration (2026-11-16)

Runs are in `runs/`. The machine was busy (builds running), so the load average was 14 to 78 and
frame times are noisy; the error and picture columns are the reliable ones.

1. `stock228-ref-20261116-105657`: stock Lichii build 228 (MoltenVK 1.4.1), the reference.
2. `mainline-asis-20261116-110547`: a local test app (Lichii `7c7f723`, MoltenVK main with the
   push-desc-16 patch, libMoltenVK sha1 88501a77). Against 1: no picture regressions except `walk2-r1` (lighting
   and exposure of the ground differ between the two Lichii builds; same spot, x -27.00 vs -26.98). Errors:
   `compute_buffer_index` 0 -> 5 (the known 5 compute shaders), `pipeline_failed` 0 -> 1, `sampler_array_limit`
   152 -> 0. Positioning held across builds: stock walked at ~42 ms a frame and this build at ~75 ms, and every
   shot landed within 0.1 to 8 on the position panel (spawn 0.30).
3. `mainline-unmodified-mvk-20261116-113109`: a private copy of 2 with the unmodified MoltenVK main
   (`libMoltenVK.dylib.unmodified-5189f8d`, sha1 d4b77175), the known-bad case. Against 2 (the same Lichii build):
   `stage_resource_limit` 0 -> 35, `pipeline_failed` 1 -> 10, and 7 of 8 shots FAIL with 12% to 34% of tiles
   changed (noise between good runs: at most 4.7%). By eye: the canopy at the top of the spawn shots is gone, with
   white sky showing through. The one shot that passed (`walk2-r2`, 8.7%) faces close geometry.

## Not done / limits

- The route is measure.sh's: some of its shots face close geometry (a tree trunk at `r2`). Canopy and sky are
  mainly checked by the spawn shots. A route with more sky would make the picture check stronger.
- Only the window capture (1x, 1280 points) is compared. HDR, post-processing and internal-resolution differences
  between builds would all show up as changed tiles.
- Comparing two different Lichii builds also compares their own rendering differences. Use a reference of the same
  Lichii build with a known-good MoltenVK when one exists.
- Each run rewrites the shared shader cache (`lichii-cache.v2.bin`, `vulkan_pipelines.fork-v54.bin`). Switching
  between build 228 and the nx2 builds makes the next boot rebuild pipelines (63 s instead of 3 to 12 s), so the
  first standing phase after a switch is slower. `result.json` → `shader_cache_changed` lists the files.
