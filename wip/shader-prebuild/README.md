# Prebuilding shaders before play (Lichii on the M4 Pro, MoltenVK)

**Answer.** The mechanism works on this Mac, but the full file does not stay prepared.

- Lichii can build pipelines from a predicted file before play, and Metal's on-disk cache then answers those
  compiles during play.
- In a held-out test (a save load whose pipelines were partly unknown to the training cache), shader compile work
  during play fell from 175.6 s to 7.3 s. Time lost to long frames fell from 56.6 s to 10.4 s, against a floor of
  8.9 s with everything cached. The file in that test was small enough for Metal's cache.
- The full file of 311,091 pipelines prepares to the end in about 105 minutes. But Metal keeps **at most 1 GiB per
  cache file** and evicts the oldest entries. No setting raises the limit
  ([metal-shader-cache.md](metal-shader-cache.md)).
- Two ways forward:
  - **a trimmed file that fits.** One is built, but it is not yet prepared or tested.
  - **binary archives in MoltenVK**, which keep prepared pipelines in files the emulator owns
    ([binary-archives.md](binary-archives.md)). About 7 days of work.

Nothing is installed in `/Applications/lichii.app`. What was posted upstream is in [upstream.md](upstream.md).

Everything was measured on 2026-11-17. Each number is **measured** (with its run label under
`wip/shader-prebuild/local/emulator-prebuild/runs/`), **inferred**, or **reported** by a named public source.

| File | What it covers |
| --- | --- |
| this README | how it works, the measurements, status and what to do next |
| [metal-shader-cache.md](metal-shader-cache.md) | Metal's cache: the 1 GiB clamp, eviction, the hit/miss log, rules for relying on it |
| [binary-archives.md](binary-archives.md) | the route past 1 GiB: probe results and the MoltenVK plan |
| [precompiled-file.md](precompiled-file.md) | the builder, what was wrong in the file and fixed, what is still wrong, coverage, ways to shrink it |
| [tour-plan.md](tour-plan.md), [material-decoder.md](material-decoder.md), [extended-dynamic-state.md](extended-dynamic-state.md) | the three plans for a smaller file that covers more |
| [upstream.md](upstream.md) | the six posts and what each is waiting for |
| `unfinished/…/main-decompile/` in the glitch-research repository | decompiling the game's `main` with IDA (used for the decoder) |
| `scripts/`, `patches/`, `data/` | the harness, probes, analysis scripts, the Lichii patch, and two raw outputs |

## How it works

1. **Lichii PR #1366** is open upstream ("precompiled pipelines from the player's own play"). It reads the `.nup`,
   extracts every shader program (56,382 here) and the tables of which programs are drawn together (33,253
   vertex/pixel pairs), and writes a "precompiled file" of pipeline records. It merged cleanly onto the local build
   (all-in-one + path-60); one compile error from the merge was fixed.
2. **Preparation.** The emulator builds every record once and then drops the pipeline. Metal's cache keeps the
   compiled code, and Lichii keeps each pipeline's translated shader.
3. **At draw time** a pipeline whose key was predicted is created from the kept translation. Any other pipeline is
   translated as usual, and its Metal compile is answered from Metal's cache if that shader and state were prepared.

### What had to change for Mac

| Change | Why | Where |
| --- | --- | --- |
| Preparation enabled on MoltenVK | Upstream skips it where the driver has no pipeline cache of its own. Metal has one, per bundle id | `vk_pipeline_cache.cpp` |
| Preparation passes no `VkPipelineCache` | MoltenVK holds one lock across every conversion and compile that shares a cache (MoltenVK #2863). Without it, seven compiles run at once (**measured**: `MTLCompilerService` at about 650% CPU) | `vk_pipeline_cache.cpp`, `.h` |
| 256 MiB stacks for shader worker threads | SPIRV-Cross walks control flow recursively and overflowed the 512 KiB macOS thread stack on one compute program (**measured**: crash in `t1-cold`; reported as MoltenVK #2907) | `shader_jobs.cpp` |
| A state model for Mac keys | Upstream predicts keys only for GPUs with dynamic vertex input, which gives 0 predictions here (**measured**). A key covers 432 bytes here, including the vertex layout | `py/state_model_static.py`, `py/build_precompiled.py --static` |

The patch with all of this, plus the builder fixes of [precompiled-file.md](precompiled-file.md), is
[patches/lichii-prebuild-on-pr1366.patch](patches/lichii-prebuild-on-pr1366.patch).

The Lichii worktree it was made in was removed on 2026-11-17; nothing in it was lost. To recreate it at
`local/emulator-prebuild/lichii` in this folder, run from the repository root after `./build.sh fetch`:

```bash
S=$PWD/wip/shader-prebuild
git -C build/src/lichii fetch origin pull/1366/head:pr1366    # PR head eee197a9fc at the time
git -C build/src/lichii worktree add "$S/local/emulator-prebuild/lichii" -b prebuild gold~2   # the pinned source before the shared JIT cache
cd "$S/local/emulator-prebuild/lichii"
git merge --no-edit pr1366                                    # merged cleanly on 2026-11-17
git apply "$S/patches/lichii-prebuild-on-pr1366.patch"
```

`gold~2` is patch 0006 of `patches/lichii/`, the state this work was done on; it has not been tried on top of the
shared JIT cache.

Then build with `scripts/prebuild/build.sh`. That is a full build: the old build tree went with the worktree.

## Measurements

### The design rests on two facts

- **Metal keeps what was compiled.** 5,114 pipelines took 198.3 s cold and 3.5 s when prepared again (`t2`,
  `t3-warm-force`). **Measured.**
- **Metal compiles and caches the two halves of a pipeline separately.** A new blend state or colour format costs
  about 200 ms (fragment half). A new vertex stride or vertex function costs about 10 ms. A new depth format costs
  0 ms. **Measured.** So the file covers each shader's likely states once, not every combination: per pair, the most
  likely state, then 5 more render-target states, 3 more vertex layouts and 1 more topology.

### First-visit test

Same load each time: boot, menus, load the top save, stand. Each run used empty Lichii caches and a fresh Metal
cache (an app copy with its own bundle id). The top save loads into a desert canyon, not Kokiri Forest, so the
harness did not walk its route; the runs are still alike. The training cache lacked 192 of the canyon's 509
graphics pipelines. **Measured** (`scripts/prebuild/exp.sh`, `scripts/prebuild/hitches.py`).

| Run | Label | Compile work on workers | Time over 33 ms | Frames over 250 ms | Worst frame |
| --- | --- | ---: | ---: | ---: | ---: |
| Nothing prepared | `exp-base` | 175.6 s | 56.6 s | 14 | 20.1 s |
| Recorded pipelines and all compute prepared (upstream's model) | `exp-rec` | 92.2 s | 24.8 s | 10 | 6.8 s |
| Predicted pipelines too (Mac model, trained on the older cache only) | `exp-pred2` | 7.3 s | 10.4 s | 8 | 3.8 s |
| Everything already cached (floor) | `exp-ref` | 2.7 s | 8.9 s | 6 | 3.8 s |

- One run each, so the spread is not known.
- `exp-pred` is void: its predicted keys carried a device bit of the older build, which Lichii skips without a
  warning ([precompiled-file.md](precompiled-file.md)).
- One compute pipeline (`b6af6ff137fc7d85`) still built on the GPU thread in 2.9 s in `exp-rec` (9.6 s unprepared).
  Its recorded pointer state was not the one the game used; the live cache has the right state.
- `exp-pred2`'s preparation left about 300 MB of Metal cache, well under the cap.

### The full file

- 311,091 records (4,789 recorded graphics, 294,821 predicted vertex/pixel, 7,423 predicted mesh, 4,058 compute)
  in 1,306,267,932 bytes, trained on all three saved caches. It passes `nx2-precompile check`. **Measured.**
- Preparation takes about 105 minutes on seven driver threads and can be resumed (`t4-full-cold`, then
  `t5-full-resume`). Peak memory was 7.2 GB, and 20 distinct records fail every time
  ([precompiled-file.md](precompiled-file.md)). **Measured.**
- Lichii's kept translations come to 914 MB plus a 28 MB index. **Measured.**
- Metal's two cache files stopped at about 1.2 GB each, 16 minutes into the pass. A repeat ran at the cold rate
  from its first record, and so did a repeat with a raised size value (`t6`, `t14`). That matches the 1 GiB clamp.
  **Measured.**

The file is prepared most-likely-first and eviction is oldest-first, so an overflowing file keeps its least likely
part.

### The trimmed file

One state per pair. The current version, `static-top1-v2.nx2prep`, has 38,931 records in 919 MB. It includes the
two builder fixes (146 recovered pipelines, 1,857 never-drawn pairs dropped). It has not been through
`nx2-precompile check` or a preparation yet.

Its predecessor (`static-top1`, 42,629 records) passes the check. Its cold preparation `t15-top1-cold` was stopped
after two minutes, so it gives no result.

In the held-out table, one state per pair covered about 37% of new fragment-side compiles. That is **inferred**
for this file, not measured. By the estimate in [metal-shader-cache.md](metal-shader-cache.md), it should fit
Metal's cache.

## Status

- **Done and measured:** the Mac changes, the held-out first-visit test, and two complete preparations of the full
  file.
- **Closed:** keeping the full file in Metal's cache. The 1 GiB per file limit cannot be raised.
- **Built, unchecked:** the `-v2` files (full and trimmed). The cleanup run that built them was stopped before it
  ran the file check and before it rebuilt the app with the run-time skip log.
- **Not installed:** `/Applications/lichii.app` and its Metal cache were not touched.
- The user's emulator config and shader folder are back to the pre-session backup
  (`wip/shader-prebuild/local/emulator-prebuild/user-state-backup-2026-11-17/`), except `audio_muted=true`.

## What to do next

In order. Steps 1–3 need no emulator.

1. **Finish the cleanup (about 1 h, mostly building).** Recreate and build the Lichii worktree (above). Run its
   `nx2-precompile check` on `static-top1-v2` and `static-v2`. Then refresh `prebuild/app/lichii.app` from the
   build (that app is the build plus path-60's MoltenVK), so the run-time skip log is in.
2. **Binary-archive scale probe (0.5 day, standalone).** Step 1 of [binary-archives.md](binary-archives.md). It
   decides whether the 7-day route is sound before any MoltenVK work. A first attempt was stopped before it
   produced results.
3. **Small builder fixes.**
   - Raise `--kd` (free in Metal; 82 of 273 held-out "new state" keys).
   - Make `game_tables.py` skip hash 0.
   - Reproduce the two failing compute programs (SPIRV-Cross nesting) and the mesh compiler crash offline.
4. **Verify the trimmed file (about 2 h, emulator).**
   - Prepare it cold with `MTL_LOG_COMPILE_STATS=2` and `oslogtap.dylib`, so Metal itself reports what it kept.
   - Replay it warm.
   - Rerun the first-visit test with it, and check the 9.6 s compute pipeline in the same runs.
   - If it passes, install it for the daily app.
5. **Reboot test (30 min plus a reboot).** Check that Metal's cache survives a restart. If not, try
   `FS_CACHE_REUSE_ON_REBOOT=1`.
6. **One MoltenVK rebuild, tested one change at a time (3–4 h, emulator).**
   - Build with the private API, so `provokingVertexLast` is reported. The stock app has it and the prebuild app
     does not, and this is suspected as the cause of the grass flashing.
   - Add MoltenVK PRs #2901 and #2905, which help cold boots; see
     [../emulator-options/README.md](../../research/emulator-options/README.md).
   - Note that turning on last-vertex mode changes key bit 12 again, so the file must be rebuilt for that device.
7. **Bigger routes, the user's decision.**
   - Binary archives (about 7 days): the full file fits, and the next three become optional.
   - The fly-through tour (3–4 days), the material decoder (3–5 days, go/no-go at 1.5) and extended dynamic state
     (7–9 h): these exist to make a trimmed file cover more.
8. **Upstream:** wait for the replies listed in [upstream.md](upstream.md), above all HyperCed's on PR #1970.

## Not measured

- The trimmed file's preparation time, Metal cache use, warm replay and effect in play.
- The spread of any result: every run here is one run.
- A walk through an area no cache has seen, with any file. The canyon test is the nearest.
- Frame rate while preparing in the background ("While playing"). Only "Before the game starts" was used.
- The picture against the practice build. The merged build draws the canyon (`runs/exp-base/shots/_poll.png`).
- How the cache behaves once play adds its own entries on top of a full one.

## What is kept where

Under `wip/shader-prebuild/local/emulator-prebuild/` (git-ignored):

- `app/lichii.app`: the prebuild app (without the run-time skip log), bundle id `io.github.zortos293.lichii.prebuild`.
  The Lichii worktree is gone; see "What had to change for Mac" to recreate it.
- `eval/out-all/`: the builder's inputs and outputs.
  - Inputs: `inventory.json`, `nx_pairs.json`, `scan.envs`, `game.programs`, the three training caches
    `cache1..3.fork-v54.bin`, and `drop-dynamic3.json`.
  - Outputs: `static-v2`, `static-top1-v2`, `static-top1` and upstream's `precompiled.fork-v54.nx2prep`, each with
    its report.
- `eval/*.fork-v54.bin`: the recorded caches (`orig`, `live`, `canyon-base`). `eval/*.py`: the evaluation scripts,
  also in `scripts/prebuild/`.
- `runs/`: one folder per run label (`stderr.log`, Lichii log where reached, size samples).
- `user-state-backup-2026-11-17/`: the user's shader folder and config from before this work.
