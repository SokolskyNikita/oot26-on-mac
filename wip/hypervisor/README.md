# Hypervisor CPU backend: unfinished work

Everything that survives of the work on Lichii's Hypervisor.framework CPU backend, collected so it can be resumed.
Paths are relative to the `oot26-on-mac` root unless they start with `/`. Every claim is tagged:
**[measured]** (from a harness run), **[code]** (read from the source), **[suspected]** (a hypothesis nobody has
tested yet).

**State in one paragraph.** The backend runs the game's ARM code natively and, with the patches here, is faster
than the JIT at the Kokiri Forest spawn and has no walk hitch [measured]. The render race that broke the picture
(dark band, missing HUD) is found and fixed [measured]. About one Hypervisor boot in twelve still comes up with a
corrupted picture [measured]. A cause is suspected and a fix is written (`EDEN_NX2_HVF_INTERPRET_READS=1`), but
that fix has never been booted. Do not make Hypervisor the default until section 5 is settled.

## 1. What the Hypervisor backend is, and why it matters

- **What it is [code].** Upstream Lichii PR #1970 (HyperCed) adds `cpu_backend = Hvf` (value `2` in
  `qt-config.ini`). It runs the guest's AArch64 code directly on the Mac's CPU inside a Hypervisor.framework VM.
  It replaces only the JIT (dynarmic) for game code; GPU emulation, services and everything else are unchanged.
  The PR is commit 0001 of the pinned series (`patches/lichii/0001-Merge-Lichii-PR-1970-HyperCed-…patch`), so
  the backend is in the pinned build already, unpatched and not the default.
- **How it meets the GPU's memory tracking [code].** Pages the GPU holds a copy of are write-protected (and
  read-protected under reactive flushing). A guest store to such a page traps out of the VM; the fault handler
  (`ArmHvf::HandleDataAbort`, `src/core/arm/hvf/arm_hvf.cpp`) runs that one instruction in software
  (`InterpretAccess`) so the GPU caches hear about the write.
- **Why it matters [measured].** Kokiri Forest spawn, 300-frame walk and stand, two runs each, MoltenVK with PR
  2901 and the mesh cull-mode fix (sha1 `17f76f69f2`), load average 6 to 12 (other sessions' builds), batch
  `tools/harness/runs/ab-20261118-000958`. Both apps predate the shared JIT code cache now in the pinned build.

  | | Walk p50 / p95 / max (ms) | Frames > 50 ms in the walk | Stand p50 / p95 (ms) | Spawn after |
  | --- | --- | --- | --- | --- |
  | JIT (`build/release`, unpatched) | 22.9 / 45.5 / 653 and 21.8 / 44.0 / 452 | 11 and 14 | 18.9 / 25.4 and 18.2 / 24.1 | 44.2 s |
  | Hypervisor, `03-hvf-final.patch` defaults | 17.5 / 19.7 / 34 and 18.0 / 20.5 / 27 | 0 and 0 | 16.7 / 17.7 and 16.7 / 17.8 | 20.0 s |

  The JIT's 450-650 ms walk frame is its code-cache flush; Hypervisor has none. The pinned build's shared JIT cache
  (512 MiB) has since reduced the JIT's hitch (its own validation: walk p95 28-30 ms, worst 51-60 ms), but
  Hypervisor has not been compared against it side by side.

## 2. The render race (fixed)

**Symptom [measured, by eye]:** with Hypervisor, a dark band and a missing HUD in motion; the watches panel jumping.

**Mechanism [code, then measured].** Caching a region (`RasterizerMarkRegionCached(cached = true)` in
`src/core/memory.cpp`) was two steps on the GPU thread: (1) protect the region, kicking every vCPU out to flush
its TLB, then (2) mark each page `RasterizerCachedMemory`. The Hypervisor fault handler treats a page that is
protected but not marked as a leftover protection and gives it back read and write. A store that faults between
(1) and (2) therefore made the page writable just before it became cached; every later write to it went unseen by
the GPU until the page left the cache. The JIT does not have this: its slow path writes the bytes and leaves the
protection, so the next write faults again and finds the page marked.

**Evidence [measured]** (`tools/harness/runs/ab-20261117-203916`, load 50-85 so no frame times):

| Build | Race warnings in about 2.5 min | Write faults not interpreted |
| --- | --- | --- |
| patch 01 (log only) | 25 (22 writes, 3 reads; four store sites) | 1-5 a second |
| patches 01 + 02 (mark before protect) | 0 | 0-1 a second |

**The fix, in `patches/03-hvf-final.patch` [code]:** pages are marked before they are protected
(`Memory::Impl::ProtectForCaching`), and after the handler restores a page's kernel permissions it calls
`Memory::ReprotectIfCached`, so every interleaving of the two threads ends with a cached page protected. The log
line "became GPU-cached while its protection was being lifted" counts the re-protections; it did not fire in about
40 boots [measured]. The JIT is unaffected in frame time by mark-before-protect [measured, one run].

**Store interpreter cleared [measured]:** `scripts/hvf-interp-test/` runs random instructions on the Mac's CPU and
through the interpreter and compares: 0 mismatches in 1.26 million compared instructions (890,463 general
loads/stores, 110,419 single-element `ST1`/`LD1`, 262,577 `DC ZVA`). Thin coverage: `STLR`/`LDAR` about 50,
literal loads none.

## 3. Loop runner and tuning

**Why [measured]:** plain Hypervisor took about 380,000 write traps a second (the game's `memset`/`memcpy` loops
over GPU-cached pages) and was 3-5 ms a frame slower than the JIT.

**What the switches do [code]** (from `patches/experiments/hvf-experiments-2026-11-17.patch`, folded into 03):

- `EDEN_NX2_HVF_LOOP=N`, loop runner: after a trapped store, keep interpreting the following instructions (loads,
  stores, add/subtract, compare, branches) up to N, or until one it does not handle. 03 makes 256 the default.
- `EDEN_NX2_HVF_BURST=N`: the same for consecutive loads and stores only.
- `EDEN_NX2_HVF_DIRTY_ONLY`: write back only changed registers after interpreting. 03 makes it on by default.
- Also in the patch: `EDEN_NX2_HVF_STATS` (exit counters every 10 s), `_CTL`, `_SITES`, `_RAW_COUNTER`.

**Tuning [measured]** (same batch and conditions as section 1, walk p50 ms, two runs):

| Configuration | Walk p50 | Stand p50 | Worst walk frame |
| --- | --- | --- | --- |
| Defaults (loop 256, dirty-only on) | 17.5 / 18.0 | 16.7 / 16.7 | 34 / 27 |
| Loop runner off | 23.4 / 23.9 | 21.6 / 22.4 | 29 / 44 |
| Loop 64 / 1024 / 4096 | 17.4-17.8 | 16.6-16.7 | 20-35 |
| Loop off, burst 32 | 17.8 / 17.3 | 16.6 / 16.5 | 24 / 34 |
| Dirty-only off | 17.5 / 17.4 | 16.6 / 16.6 | 29 / 21 |

The loop runner is worth about 6 ms a frame; its limit does not matter between 64 and 4096; burst 32 does as
well; dirty-only makes no measurable difference. With the loop runner write traps fall to about 120,000 a second,
all interpreted, and system calls (about 160,000 a second) are the largest source of exits. No run logged a
backend error, an invalid access or a store the interpreter could not handle.

## 4. The open corruption

**Seen [measured, by eye and by score]:** `fin-default-r2` (`tools/harness/runs/ab-20261118-000958`): rainbow
shards over the foliage. `shards-hvf-r9` (`tools/harness/runs/ab-20261118-002819`): the whole scene blown out
white and pink. Each was wrong for the whole run; neighbouring boots were clean; the logs match clean runs'.
Frame times of the corrupted runs are normal.

**How often [measured]:** every Kokiri run picture of 2026-11-17/18 scored with `tools/harness/persist.py`
`picture_metrics`: Hypervisor after the swap to the #2901 + cull-fix MoltenVK 2 of 26; JIT after the swap 0 of
15; Hypervisor before the swap 0 of 9 (too few to clear anything). The JIT half of the dedicated check
(`shards-jit`, 10 boots planned) stopped after one clean boot.

**The same picture elsewhere [measured, other write-up]:** the JIT with reactive flushing off
(`EDEN_NX2_NO_REACTIVE=1`, `research/emulator-options/README.md`: blown out, rainbow colours). Concurrent-compile
MoltenVK builds (own parallel load, #2905) also produced blown-out pictures on the JIT.

**Suspected cause [suspected, from code]:** under reactive flushing (the default) a GPU-cached page has no read
permission and read traps, which re-arm on a GPU write, are off (`Memory::Impl::ReadTrapsEnabled`). The JIT sends
every such read through its slow path. The Hypervisor handler's `!write` branch does one slow-path read and then
calls `GrantCachedPageRead`, making the page readable; nothing removes that permission while the page stays cached.
Later reads see the guest copy without asking the GPU, so reactive flushing stops working for that page after its
first read. Stale read-backs (exposure, culling results) would give these pictures, timing-dependent per boot.

**Untested fix [code]:** in 03, `EDEN_NX2_HVF_INTERPRET_READS=1` makes the handler interpret every load from a
GPU-cached page (when read traps are off) instead of opening the page, and adds `read_interpreted` to the exit
statistics. It is opt-in, so 03's default is the behaviour that was measured. The binary carrying it has never been
booted.

**Also not excluded [suspected]:** the shared MoltenVK (corruption seen only after the #2901 + cull-fix swap), and
the loop runner's add/compare/branch emulation (read line by line, but only loads and stores were tested against
the CPU).

## 5. Remaining tests, in order

1. **Count the dangerous event.** Add a diagnostic that logs when the GPU writes into a page that
   `GrantCachedPageRead` opened (not written yet). Zero in every boot means the suspected cause is wrong.
2. **Force the fault.** Same spot, pictures compared: Hypervisor default; the JIT with `EDEN_NX2_NO_REACTIVE=1`
   (known bad reference); Hypervisor with `EDEN_NX2_HVF_INTERPRET_READS=1`.
3. **Cost of interpreting every read:** `specs/read-path.json` (6 boots, two with exit statistics).
4. **Only then repetition:** `specs/shards-rate.json`: 10 boots each of Hypervisor default, Hypervisor with the
   read fix, and the JIT on the same MoltenVK, every picture scored, `on_corrupt` capturing a GPU trace and a frame
   with buffers on any corrupted boot. Thirty clean boots alone give only about 92 % confidence at a 1-in-12 rate.
5. If the read path is cleared: test the MoltenVK (same boots on the pre-#2901 library) and extend
   `scripts/hvf-interp-test` to the loop runner's ALU and branch handling.
6. 5-minute walks (18,000 frames, 45 m leash), Kokiri Forest and Gerudo Valley, best Hypervisor against best JIT:
   `specs/walk5.json`. Never run.
7. ThinLTO Hypervisor (`scripts/build-final.sh build/release-lto hvf-final-lto`, after configuring that tree) against the best JIT, then against the current pinned
   build with the shared JIT cache; other maps including a map change.
8. Measure on an idle machine with several runs per setup (every Hypervisor number so far was taken at load 6-16).
9. Smaller open items: the JIT-with-fix run that booted in 52.8 s against 16.5 s (one run, never looked at);
   whether macOS keeps a vCPU's TLB entries when its thread changes core (the flush uses `TLBI VMALLE1`, local to
   the current core); upstream issues zortos293/Lichii #1380 / #1381 and PR #1367 never checked against this race;
   nothing reported upstream.

Smoke-test one boot of any rebuilt app before queueing a batch, and look at the recorded pictures: both
corruptions had clean logs.

## 6. What is here and how it maps onto the pinned source

The patches were made against the series pinned until 2026-11-19 (`8c0558a3d3` plus 8 patches); what follows
describes that source. On the series pinned now (`d2ca32974d` plus `patches/lichii/0001`-`0007`, branch `gold` in
`build/src/lichii`) all three pass `git apply --check` (2026-11-19, not built). The three files the Hypervisor patches touch (`src/core/arm/hvf/arm_hvf.cpp`,
`src/core/memory.cpp`, `src/core/memory.h`) are byte-identical in every commit from 0001 (`a5ec919891`, the PR
#1970 merge) to `gold`, and in the tree (HEAD `44532bbe15`, since deleted) they were made
against. So every patch here was made against "the series from 0001 on", and all of them apply.

| File | What | Applies to `gold`, `gold~1`, `gold~2` |
| --- | --- | --- |
| `patches/01-count-dropped-protection.patch` | Diagnostic: warn when the handler opens a page that is cached | Yes (`git apply --check`), alone or after the experiments patch |
| `patches/02-mark-before-protect.patch` | Mark pages before protecting them (made on top of 01; also applies alone) | Yes |
| `patches/03-hvf-final.patch` | The whole change against the pristine files: experiments + 01 + 02 + `ProtectForCaching` / `ReprotectIfCached`, loop 256 and dirty-only on by default, opt-in `EDEN_NX2_HVF_INTERPRET_READS` | Yes (498 lines, the same length as the one that built `app-hvf-final`) |
| `patches/experiments/hvf-experiments-2026-11-17.patch` (tracked, outside this folder) | Loop runner, burst, dirty-only, stats switches (only `arm_hvf.cpp`) | Yes. 03 contains all of it; do not apply both |
| `scripts/make-final.py OUTDIR` | Generates 03 from the pristine files of `build/src/lichii` + the experiments patch + 01 + 02 | Reproduces `patches/03-hvf-final.patch` byte for byte (checked 2026-11-19, with the files' times set to the ones in 03's headers) |
| `scripts/build-final.sh [BUILD [NAME]]` | Builds `build/hvf/app-NAME/lichii.app` from 03 by recompiling two `.cpp` files into a copy of a build tree's `libcore.a` and relinking; never touches the source or the build tree | Needs `build/src/lichii/BUILD/compile_commands.json` (default `build/release`, made by `./build.sh`) and the pinned app |
| `scripts/build-apps.sh` | Builds the race test apps (`build/hvf/app-hvfrace-base/-diag/-fix/-fast`) the same way | Same, `build/release` only |
| `tools/harness/persist.py` (moved there) | Per-pixel persistence of white over a burst; `picture_metrics(png)`: `clipped_pct`, `vivid_pct`, `corrupt` (clipped > 15 % or vivid > 0.15 %) | Used by the harness on every run |
| `scripts/hvf-interp-test/` | Interpreter-vs-CPU differential test (`run.sh N SEED`; needs `LICHII=` a built tree) | Its copy of the `DC ZVA`/`ST1` code must track `arm_hvf.cpp` |
| `specs/*.json` | Harness specs: `hvfrace`, `hvffast`, `final-tune` (section 3 batch), `shards-rate`, `read-path`, `walk5`, `wall`, `kokiri-debug`, `resave` | Apps are `${REPO}/build/hvf/app-NAME/lichii.app` (none built yet) or, for the JIT reference that was `app-mvkp2901`, the pinned app `${REPO}/build/app/lichii.app` |
| `render-bug-writeup.md` | The full original write-up, sections 1-6 (paths rewritten) | |
| `rendering-faults/README.md` | Catalogue of every rendering fault found up to 2026-11-17 and a playbook for the next one | General, not Hypervisor-specific |

**Paths in the scripts and specs.** The scripts find the repository with `git rev-parse --show-toplevel` and use
this layout: the pinned Lichii source `build/src/lichii` (branch `gold`; `LICHII_SRC` for another tree) and its build
tree `build/src/lichii/build/release`, both made by `./build.sh`; the experiments patch
`patches/experiments/hvf-experiments-2026-11-17.patch`; patches 01-03 in `patches/` here. Test apps go to
`build/hvf/app-NAME/lichii.app`, work files to `build/hvf/work/` (ignored by git). Each test app is a copy of the
pinned app `build/app/lichii.app` with its own `lichii` binary, so it carries the pinned `libMoltenVK.dylib` (the
shader caches stay valid; a different library makes the next boot compile every shader again), the pinned
`nx2_switches.txt` (which turns on the shared JIT cache; the Hypervisor backend does not use the JIT for game code)
and the pinned Info.plist. Specs name apps as `${REPO}/…`, which the harness expands.

**Running the scripts.** Nothing here has been built or run since the recovery. From the repository root, after
`./build.sh`:

```bash
python3 wip/hypervisor/scripts/make-final.py /tmp/hvf-final   # optional check: diff /tmp/hvf-final/hvf-final.patch with patches/03
wip/hypervisor/scripts/build-final.sh                          # -> build/hvf/app-hvf-final/lichii.app
wip/hypervisor/scripts/build-apps.sh                           # -> build/hvf/app-hvfrace-{base,diag,fix,fast}/lichii.app
wip/hypervisor/scripts/hvf-interp-test/run.sh 100000 1         # interpreter vs CPU; no emulator needed
```

`build-final.sh` runs `make-final.py` into `build/hvf/work/final` when that folder has no patched files yet; delete
it after changing `make-final.py` or its inputs. Then the specs, each under the emulator lock. Boot a new app once
first and look at its pictures (both corruptions had clean logs):

```bash
cd tools/harness
./queue.sh ../../wip/hypervisor/specs/read-path.json      # cost of EDEN_NX2_HVF_INTERPRET_READS (app-hvf-final)
./queue.sh ../../wip/hypervisor/specs/shards-rate.json    # corruption rate, 3 x 10 boots (app-hvf-final, the pinned app)
./queue.sh ../../wip/hypervisor/specs/final-tune.json     # the section 3 tuning batch (app-hvfrace-base, app-hvf-final)
./queue.sh ../../wip/hypervisor/specs/hvfrace.json        # the race, logged and fixed (build-apps.sh's apps)
./queue.sh ../../wip/hypervisor/specs/hvffast.json        # the speed switches (build-apps.sh's apps)
./queue.sh ../../wip/hypervisor/specs/wall.json           # bursts at the cave wall (build-apps.sh's apps, app-hvfrace-ltojit)
./queue.sh ../../wip/hypervisor/specs/kokiri-debug.json   # cave-wall bursts under several switches, on the pinned app
./queue.sh ../../wip/hypervisor/specs/walk5.json          # 5-minute walks (app-hvf-final-lto, app-hvfrace-ltojit)
./queue.sh ../../wip/hypervisor/specs/resave.json         # load the forest save and hold; rm wip/hypervisor/local/HOLD to go on
```

`app-hvf-final-lto` needs a ThinLTO build tree (`scripts/build-final.sh build/release-lto hvf-final-lto`), and
`app-hvfrace-ltojit` is that tree's own JIT app copied to `build/hvf/app-hvfrace-ltojit/` with the pinned
`libMoltenVK.dylib`. `./build.sh` makes neither, so `wall.json`'s last run and `walk5.json` need such a tree
configured by hand first. `walk5.json` also needs a Gerudo Valley save (`GerudoValley_Child`).

**Harness changes**, merged into `tools/harness/ab.py` on 2026-11-19 and documented in its README:
`build_wait: false` (do not wait for builds), `resave: true` (Plus, R, A, Up, A, B
right after the load), `hold_file` / `hold_max_s` (hold the game for manual debug-server calls), `walk_shots`
(screenshot per walk chunk; changes the walk, do not combine with an end burst), `stand_frames`, `at_end` (steps
from `tools/speckcheck/speckhunt.py`), `leash_m` (turn round when that far from the start, for long walks; never
run), and for every run a `picture` score in `result.json` plus `on_corrupt` steps that run only on a corrupted
boot (`on_corrupt` has never triggered; the score rated the two smoke runs of 2026-11-19 clean). Each option is off
unless a spec sets it. `ab.py` imports `persist` from its own folder and `speckhunt` / `whitecount` from
`tools/speckcheck/` (a newer superset of the copy that was in `97efae6`). `scripts/run-ab.py`, which ran a worktree
copy of the harness, is gone: the main harness has the options now.

**Rendering-faults catalogue.** Written before the white specks were solved: its section 2.2 says "fix in
progress"; the fix (MoltenVK mesh cull mode) is now in the pinned build, see `research/mesh-white-specks/`. Two
tools it names, `pairdiff.py` and `metal-validation/run_to_spawn.sh`, are not in this repository.

## 7. Built apps and run data on disk

| Item | State |
| --- | --- |
| `app-hvf-final` (deleted 2026-11-19 with the old build trees; rebuild with `scripts/build-final.sh`) | Binary 2026-11-18 00:43, sha1 `b3fde34a2d0e…`; carries 03 exactly (contains `EDEN_NX2_HVF_INTERPRET_READS` and the re-protect log text, no `EDEN_NX2_HVF_GRANT_READS`); MoltenVK `17f76f69f2`; hypervisor entitlement present; `nx2_switches.txt` without the shared-JIT line; built from the old tree's `build/release`, so no shared JIT cache. Never booted in this exact form |
| `app-hvfx` (deleted 2026-11-19) | 2026-11-17 16:27, sha1 `5c1bf286719e…`: the earlier burst/loop experiments only (no race fix), old MoltenVK `aa7120ae18` |
| Source trees | No tree under `build/` carries any of these changes; `build/src/lichii` and the old trees (`build/old-trees/path-60/lichii` have only upstream's `EDEN_NX2_HVF_STATS`. The two `mvk-backups/*.tar` hold no Hypervisor files. `mvk-backups/app-hvf*.libMoltenVK.before-cullfix-*.dylib` are only MoltenVK copies |
| Run folders in `tools/harness/runs/` | `ab-20261117-160732` (15 MB: `hvf-r1`, `hvf-r2`, `hvf-stats`), `-203916` (3.9 MB: `hvfrace-diag`, `hvfrace-fix`), `-204540` (12 MB: `hvffast-*`, 6 runs), `ab-20261118-000511` (2 MB: `fin-smoke`), `-000958` (34 MB: 17 `fin-*` runs), `-002819` (22 MB: `shards-hvf-r1`…`r10`, `shards-jit-r1`, an incomplete `shards-jit-r2`). Gone: every `wall-*`, `long-*`, `kdbg-*`, `walk5-*`, `rd-*` run |

## 8. Recovered from / missing

| Artefact | Recovered from | Completeness |
| --- | --- | --- |
| Patches 01, 02 | Commit `97efae6` | Complete |
| `03-hvf-final.patch` | Regenerated with the recovered `make-final.py` from the old tree's files (unchanged since) + the tracked experiments patch + 01/02 | Complete; 498 lines like the original. Not byte-compared with the lost original (the original file is gone), but its generator is the exact final version and its inputs are unchanged |
| `make-final.py` | Final `Write` replayed with its three later in-place edits from the transcript; matches the file-history copy except the last edit (opt-in switch), which the transcript has | Complete |
| `build-final.sh` | Transcript (heredoc) | Complete |
| `build-apps.sh`, `run-ab.py`, interpreter test | Commit `97efae6` (also identical in file history) | Complete |
| Specs `hvfrace`, `hvffast`, `wall`, `kokiri-debug`, `resave` | Commit `97efae6` | Complete. One-off specs deleted before the end (`longwalk`, `hvffast-loop-watch`, `kokiri-debug2/3`, `resave-check`) are still in `97efae6` if needed |
| Specs `final-tune`, `shards-rate`, `read-path`, `walk5` | Transcript (Python heredocs replayed in order) | Complete, final versions |
| Write-up sections 1-4 | Commit `97efae6` | Complete |
| Write-up sections 5-6, status line | Transcript (heredoc), replayed onto the commit's file | Complete |
| `ab.py` options (`build_wait`, `stand_frames`, `at_end`, `walk_shots`, `hold_file`, `resave`) | Commit `97efae6` | Complete |
| `ab.py` `leash_m`, `picture` score, `on_corrupt`; README text | Transcript, replayed; result identical to the file-history copy of `ab.py` and the harness README | Complete |
| `persist.py` incl. `picture_metrics` | Commit `97efae6` + transcript edit | Complete |
| Rendering-faults catalogue | Commit `97efae6` + one later transcript edit; identical to the file-history copy | Complete |
| "Where it stopped" note and the white-specks shader-bundle index | Transcript / commit | Superseded by this README; not copied |
| Offline shader bundles and GPU tests (white specks) | Were in an ignored `local/` folder of a removed worktree | Missing. Game code; the specks are solved |
| Diagnostic for step 1 of section 5 | Never written | Missing |
| Test apps `app-hvfrace-*`, `app-hvf-final-lto` and the build folders | Deleted | Rebuildable with the scripts |
| Runs `wall-*`, `long-*`, `kdbg-*` | Deleted | Missing; their results are in `render-bug-writeup.md` and the catalogue |
