# The precompiled file: how it is built, what is wrong in it, and how to make it smaller

The builder is `tools/nx2-precompile/py/build_precompiled.py --static` in the Lichii worktree
`wip/shader-prebuild/local/emulator-prebuild/lichii` (removed; [README.md](README.md) shows how to recreate it). The Mac state model is `py/state_model_static.py`. Local changes are in
[patches/lichii-prebuild-on-pr1366.patch](patches/lichii-prebuild-on-pr1366.patch). Inputs and outputs are in
`wip/shader-prebuild/local/emulator-prebuild/eval/out-all/`. Claims are **measured** (counts from the files or logs), **read**
(code) or **inferred**.

## What is in it

The builder writes four kinds of record:

1. every recorded pipeline from the training caches (`--train`);
2. for every vertex/pixel pair in the game's tables (`nx_pairs.json`) and every recorded pair, a list of candidate
   states from `model.candidates(vs, fs, kt, kl, kf, kd)`. That is the most likely state, then one part varied
   at a time. The defaults for `--static` are 6 render-target states, 4 vertex layouts, 2 topologies and 1
   depth/cull/stencil state;
3. predicted mesh records;
4. compute records, recorded or with an "oracle" environment.

A key covers 432 bytes of state. That includes the vertex layout, because this MoltenVK has no dynamic vertex
input and Lichii keeps extended dynamic state off on Apple.

| File | Records | Bytes | Notes |
| --- | ---: | ---: | --- |
| `static-v2.nx2prep` (full) | 292,535 | 1,195,707,377 | the current full file, with the fixes below |
| `static-top1-v2.nx2prep` (trimmed) | 38,931 | 919,407,808 | one state per pair, with the fixes below |
| `static-top1.nx2prep` (trimmed, before the fixes) | 42,629 | 1,014,120,983 | passes `nx2-precompile check`; kept as a fallback |
| `precompiled.fork-v54.nx2prep` (upstream's model) | 8,847 | 172,521,122 | recorded pipelines and compute only; the `exp-rec` baseline |

All **measured** from the build reports. The `-v2` files were built on 2026-11-17 by a cleanup run that was
stopped before it ran `nx2-precompile check` and before it rebuilt the app. So neither `-v2` file has been checked
or prepared yet.

Most of a file's size is shader environments, not records. That is why the trimmed file is still 0.9 GB.

## Fixed in the -v2 files

### Recorded keys that this device can never use (146 pipelines recovered)

Bit `0x1000` of the second state word (`raw2`, key offset 52) is `provoking_vertex_last`. **Read:**

- Lichii sets the bit only when the device reports `provokingVertexLast`.
- MoltenVK reports that feature only when built with Metal's private API (`MVKDevice.mm:793`:
  `provokingVertexLast = getMVKConfig().useMetalPrivateAPI`).
- The stock app's MoltenVK 1.4.1 has it (its dylib calls `setProvokingVertexMode:`). The prebuild app's MoltenVK
  1.4.3 does not, and every run logs "Device doesn't support feature provokingVertexLast".

So `cache1` and `cache2`, recorded with the stock app, carry the bit (2,051 of 3,109 and 2,055 of 3,745 graphics
records). `cache3`, from the prebuild app, never does (**measured**, `scripts/prebuild/count_device_bits.py`).

`KeyFitsDevice` rejects those keys, both when loading the disk cache (`LoadPipelinesV2`) and in preparation
(`PreparePrecompiled`, counted as "prepared before"). It does so without a message. In the old full file 2,019
records carried the bit and 0 of them were prepared; 1,873 had a twin with the bit clear, so 146 distinct recorded
pipelines were lost. **Measured** (`scripts/prebuild/failed_prep_records.py`, the `t4` log: "2019 prepared
before").

Clearing the bit is a safe conversion. On a device without last mode, `Refresh` turns a draw that asks for Last into
`provoking_vertex_last = 0`. The cleared key is therefore exactly what this build records for the same draw.
No cached key has transform feedback together with the bit. **Read** and **measured**. The `-v2` build converts
4,106 recorded keys and recovers 146 pipelines in the full file (178 in the trimmed one).

The same trap voided the first predicted run, `exp-pred`, whose predicted keys came from the older build.
`--scene-from` now takes the device part of the key from the current cache.

This is a picture difference as well as a cache one. The stock app draws with last-vertex provoking and the
prebuild app with first-vertex. The emulator session suspected this as the cause of the grass flashing (not
tested).

### 1,857 pairs that are never drawn

The per-draw option `gsys_assign_type` is the render pass. Its choices are named in the shader archive:
`material`, `cubemap`, `zonly`, `depthshadow`, `xlu_zprepass`, `visualize`, `dynamic0..3`, `user0`. 1,857 pairs are
used only by `dynamic3` programs, and none of them was drawn in any cache. Dropping them keeps all 682 drawn pairs.
**Measured** (`scripts/decoder/dynamic3_pairs.py` → `eval/out-all/drop-dynamic3.json`, applied with
`--drop-pairs`).

### Warning when keys do not fit

- The builder now prints one warning line and three report counts ("recorded graphics off the scene device bits",
  split into provoking vertex and dynamic state flags).
- At run time, a counter in `PipelineCache::PreparePrecompiled` logs how many records were skipped for not fitting
  the device.
- Both changes are in the patch. The app in `prebuild/app/` predates the run-time log, so it needs a rebuild.
- `LoadPipelinesV2` has the same silent skip for the disk cache and should get the same counter (not done).

## Still wrong (not fixed)

From `scripts/prebuild/unexplained_counts.py` (output in [data/unexplained_counts.out](data/unexplained_counts.out))
and `failed_prep_records.py` ([data/failed_prep_records.out](data/failed_prep_records.out)). **Measured** unless
marked.

| Count | What it is | Verdict |
| --- | --- | --- |
| 2 compute records fail in every preparation | agl_technique_pfx.sharcb `#BAHS@0x18ee08` (`9082510efbbcd227`) and `#BAHS@0x18ec00` (`aedac479bfa966d9`). Metal: `fatal error: bracket nesting level exceeded maximum of 256` in the MSL that SPIRV-Cross writes | **Bug worth fixing.** It loses two compute programs everywhere. The fix belongs in SPIRV-Cross's MSL output (force temporaries for deep expressions) or in the SPIR-V Lichii emits |
| 18 predicted mesh records fail in every full-file run | One mesh program, Model.bfsha `#BNSH@0x15a000#var7` (`4ef9b9f6abd60974`), in 3 mesh states × pixel `8dfdc4b9d04c677e` (Foliage) × 6 render states. "Mesh shader function could not be compiled" after Metal's compiler service died (`XPC_ERROR_CONNECTION_INTERRUPTED … after multiple retries`) | A Metal compiler crash in MoltenVK's mesh path. It costs 18 records that no cache recorded, plus retries each time. Reproduce offline with that mesh environment |
| 102 programs fail lowering | 40 mesh, 28 compute, 28 fragment, 5 vertex, 1 task. Causes: register shadowing 33, unsupported opcode 30, per-tap gather proofs and operands 21, call linkage 4, other 14. 25 of them are in shader files the game does not load | They cannot be prepared, because the emulator's own lowering fails them too. The fix belongs in the native lowering. None is in any cache, but a cache cannot hold a program that fails lowering, so that proves nothing |
| 10 "pairs without oracle environment", 17 "mesh draws without environments" | The same lowering failures, counted again: their `code_hash` is 0 | Harmless. `game_tables.py` (lines 112–119) should skip hash 0 |
| 941 "not-ok" in the scan, 839 of them `mesh-hash-only` | Mesh and task programs get no oracle environment by design; theirs come from the `mesh-envs` step | Harmless; the label is misleading. 87 of them were drawn and are covered |
| 3 compute "spirv-differs" | agl_ndsr_vr.pck `a107e12b6771be48`, `d9ee412f00ce399a`; agl_ndsr_vr_light.pck `a2fcaa95c5a162f3` | The oracle guesses the wrong texture format. These three are recorded, so the file is right. An unrecorded program of the same kind would be prepared for the wrong format |

## How much of the game the file covers

**Measured**, offline:

- The game's files list 33,253 vertex/pixel pairs in 894 shader files.
- The three saved caches drew 1,121 of those pairs, from 73 of the files.
- `Model.Product.110` alone lists 12,574 pairs, of which 682 were drawn (counted by `code_hash` in
  `scripts/decoder/pairs.py`; counting by fingerprint gives 12,427 and 661).

So most of what the file predicts is for pairs no saved play has drawn.

Prediction quality, held out: trained on the older cache and scored on the pipelines that only the live cache has
(`scripts/prebuild/filecheck.py`). **Measured:**

| File | Records | New fragment-side compiles covered (of 389) | New vertex-side covered (of 403) |
| --- | ---: | ---: | ---: |
| Upstream model | 7,131 | 0 | 0 |
| 1 render-target state per pair | 41,527 | 145 (37%) | 77 (19%) |
| 2 states | 74,682 | 171 (44%) | 77 (19%) |
| 3 states, 2 layouts | 137,211 | 209 (54%) | 114 (28%) |
| 6 states, 4 layouts, 2 topologies (full) | 321,379 | 354 (91%) | 148 (37%) |

The fragment half is the expensive one in Metal, about 200 ms against about 10 ms for the vertex half. Only 123 to
160 distinct vertex layouts occur in a cache, and 81% of vertex shaders are seen with one layout only.

## Ways to make a file that fits 1 GiB and still covers well

Metal keeps about 50,000–65,000 functions per bundle id ([metal-shader-cache.md](metal-shader-cache.md)). The
trimmed file is the candidate. These are the options for improving what it holds. None has been tried with the
emulator.

| Option | What it would gain | Cost | Note |
| --- | --- | --- | --- |
| Raise `--kd` (depth/cull/stencil states per pair) | Held out on cache3, 82 of 273 "known shader, new state" keys differ only in those fields (273 → 191). Those fields cost nothing in Metal | minutes, offline | No emulator risk. Not tried |
| Rank pairs by render pass | Put `material`, `zonly`, `depthshadow` and `xlu_zprepass` first and `dynamic3` last (the `dynamic3` drop is done) | about 0.5 day, offline | Part of the decoder plan, step 2 |
| Fly-through tour | Exact records for every area a scripted flight reaches; unreached groups keep 1–2 states per pair. About 45,000–65,000 records | about 3–4 days, 10–13 h of emulator time | [tour-plan.md](tour-plan.md) |
| Material decoder | Probably adds no pairs: the archive's key list looks built from the game's own materials. Vertex layouts and render states from model files could help the vertex side (37% today) | 3–5 days, go/no-go at 1.5 | [material-decoder.md](material-decoder.md) |
| Extended dynamic state (EDS2) | Keys per shader combination drop 17% and extra states 31%; no Metal compile changes. Worth at most about 1.5 s of long frames in the canyon test | 7–9 h; go/no-go about 1 h | [extended-dynamic-state.md](extended-dynamic-state.md). Risk: blank picture, the reason Apple defaults to off |

With binary archives ([binary-archives.md](binary-archives.md)) the full file fits, and these options become
optional.
