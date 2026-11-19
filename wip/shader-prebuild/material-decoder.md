# Material decoder: plan

A reader for the game's shader archives and model materials, to predict pairs and states from game data instead of
from play. Planned on 2026-11-17 offline. Four game files were unpacked into a scratch folder (not kept): `Model.Product.110` bfsha, `MergeShader` bfsha, `ExternalBinaryString.bfres` and one model,
`Model/Land_Deku_Room_A.Land_Deku_Candle_A_01.bfres`. Every statement below is marked **verified** (with how) or
**assumed**. The scripts are in `scripts/decoder/` (`fsha.py`, `opts.py`, `keys.py`,
`pairs.py`, `drawn.py`, plus `dynamic3_pairs.py`). The code that reads these files in the game was found with IDA:
see `unfinished/…/main-decompile/` in the glitch-research repository.

## Verdict

**The decoder can be built, and reading the shader side is easy. As specified, though, it will probably add
nothing: the precompiled file already holds every `Model.Product` pair, and the shader archive looks like it was
compiled from the game's own material list, so "the variants materials use" is probably close to "every variant
in the archive".**

- **The full file already covers every pair.** `static_report.json` lists 294,821 predicted vertex/pixel records
  and only 10 pairs without an environment, out of 33,253 pairs (**verified**, read from the file). So for
  `Model.Product` the decoder cannot add recall. It can only drop records, or rank them.
- **The archive is an explicit list, not every combination of options.** Shading model `model` has 243 static
  options, 216 of which take more than one value in the key table, yet only 2,218 distinct static keys exist
  (**verified**, key table). The skin-weight count `gsys_weight` is a per-draw option, but each static key comes
  with exactly one weight value and all 9 render passes. That is what you would expect if each key were built
  for one real material on a mesh with a known skin count (**assumed**). If so, decoding every material gives
  back about 2,218 keys and about 12,500 pairs, which is what the file already holds.
- **One part of it pays off without reading any model file.** The per-draw option `gsys_assign_type` is the
  render pass, and its choice names are in the archive (**verified**): `material`, `cubemap`, `zonly`,
  `depthshadow`, `xlu_zprepass`, `visualize`, `dynamic0..3`, `user0`. Grouping the pairs by pass, straight from
  the key table: 1,857 pairs are `dynamic3` only, and none of them was ever drawn. Dropping them keeps all 682
  drawn pairs (**verified**, see Evidence 3).
- **The bigger lever is state, not pairs.** Model files carry each mesh's vertex layout and each material's
  render state (the candle's strings include `src_alpha`, `one_minus_src_alpha`, `lequal`, `gequal`, `front`,
  `opaque`; **verified**, `strings`). The README puts the vertex-side coverage of new compiles at 37%. A reader
  for model files is most useful if it feeds those states to the state model (TODO step 9).

**Estimate.** The decoder as specified takes **3 to 5 days** of focused work. At the low end, material option
values hash straight to keys in the key table, and the decompiled reader (`sub_431460`) names the options the
engine sets itself. At the high end, many material keys find no match and the engine-set options have to be worked out from
the data. **There is a go/no-go point at about 1.5 days (step 4).** If materials turn out to use (nearly) every
key in the archive, stop there. Only the pass ranking (step 2, about half a day) is then worth keeping.

**Where the time goes.** The shader side is nearly free: its layout is decoded below, and a
public reader for this exact version exists for `MergeShader`. The model side is the unknown: format 10.4 with
names stored as 64-bit hashes in a shared string file. And most of the expected benefit is in doubt, for the
reasons above.

## TODO

Code location: Python in `extractor/shaders/`. That folder has `ootx`'s `.nup` reader, the existing
`bnsh_extract.py`, and it is the project's own git. It writes to `dump-out/shaders/` (not committed). Only a
small consumer goes into `wip/shader-prebuild/local/emulator-prebuild/lichii/tools/nx2-precompile/py/build_precompiled.py`: a
`--pair-rank FILE` option. The format readers do not go there, because they are specific to this game and
`nx2-precompile` is the generic upstream PR. sloperina's `uishader.c` is GPL-3.0: use its offsets as facts and do
not copy its code.

1. **BFSHA option and key reader** (3–4 h, needs nothing). Write `extractor/shaders/bfsha_keys.py`. Per shading
   model it reads the static and dynamic options (name, choice strings, default, mask, word, shift), the key
   table, and the map from program index to BNSH variation. It writes `dump-out/shaders/bfsha_keys.json` for the
   four `.110` archives, the ApplicationPackage bfsha and MergeShader. The scratch `keys.py`/`opts.py` already do
   most of this for `Model.Product.110`. Required check: program count = BNSH variation count = the number of
   `varN` in `game.variations.tsv` for each BNSH (true for both shading models of `Model.Product.110`).
2. **Pass ranking, no model files needed** (4–5 h: 2 h tagging, 2–3 h builder option; depends on step 1). Tag
   every vertex/pixel pair with the passes and skin weights of the programs that use it. Rank `material`,
   `zonly`, `depthshadow` and `xlu_zprepass` high and `dynamic3` last, then let the builder drop or move the
   tail. Keep this step even if the rest is stopped.
3. **BFRES 10.4 material reader, one file** (6–10 h, needs nothing). Read the model's shared shader info: the
   archive and shading-model names, then the dictionaries of options, parameters, attributes, samplers and render
   info. Then read each material's option choice strings. Resolve hashed names through
   `Shader/ExternalBinaryString.bfres` (see Evidence 1). Optional, 1 h: read Switch-Toolbox's BfresLibrary
   source (it opens these files, per `refs/kabosune/custom-maps.md`) for how version 10 ties hashes to
   names and how per-material values override the shared block. Done means: the candle's two materials print as
   `Model`/`model` plus about 35 named options with values.
4. **All models, then the go/no-go** (3–4 h; depends on steps 1 and 3). Stream every `Model/*.bfres.zs` (7,896
   files; 237 more `.bfres` live elsewhere in the romfs) out of the `.nup` one at a time, in memory, on 1–2
   workers. Do not unpack to disk. For each material, build the static key: material choices plus defaults for
   options the material does not name. Record three numbers: (a) the share of material keys found exactly in the
   key table, (b) the number of distinct keys hit out of 2,218 (and 185 for the meshlet model), (c) the pairs
   those keys reach out of 12,574. **Decision:** if (b) is 90% or more of the archive, the decoder cannot shrink
   the set. Stop, and keep steps 1–2 (and step 9 if wanted).
5. **Engine-set static options** (0.5–2 days; depends on step 4 (a)). Some static options are probably filled in
   by the engine, not by the material: `gsys_alpha_test_func` from render info, `ns_texture*_sampler` from the
   sampler assignments, and so on (**assumed**). For keys with no match, find the options whose material value
   disagrees with every nearby program, and derive them from render info and samplers. **The decompile
   shortens this step.** `sub_431460` forces five options whatever the material says (`gsys_renderstate`,
   `gsys_alpha_test_func`, `gsys_alpha_test_enable`, `gsys_pass`, `gsys_display_face_type`) from a global table;
   read the rules from it (about half a day) rather than inferring them from data (up to 2 days).
6. **Join and output** (2–3 h; depends on steps 4–5). Write `dump-out/shaders/material_pairs.json`: for each pair,
   the materials and models that reach it and the passes it is drawn in. Convert program → BNSH variation →
   fingerprints → Lichii `code_hash` through `inventory.json`. The extractor's `varN` is the BNSH variation index,
   **not** the program index (see Evidence 2).
7. **Validation** (2–3 h; depends on step 6). See "Validation design" below. The pass/fail rule is 682 of 682 at
   pair level and 440 of 440 on the strict set.
8. **Builder integration** (3 h code; depends on steps 2/6). `build_precompiled.py --pair-rank` drops or reorders
   records. Measuring it needs a preparation run of about 105 minutes and a first-visit run. Both are out of
   bounds now; schedule them when builds are allowed.
9. **Optional, likely the better payoff: state from model files** (1.5–3 days; depends on step 3). Per mesh,
   read the vertex attribute formats, strides and buffer count (FVTX). Per material, read blend, depth and cull
   from render info. Feed them to `py/state_model_static.py` as a prior. Score it with the existing held-out test
   (`eval/filecheck.py`, new vertex-side coverage now 148 of 403).

Total: steps 1–8 take 3–5 days. Steps 1–4 (about 1.5 days) are the decision point. Step 9 adds 1.5–3 days.

### Risks, most serious first

1. **Little to gain** (likely; checked by step 4). The archive's key list looks built from the game's own
   materials, and the file already holds every pair. The pair set barely shrinks, and recall cannot rise.
2. **Engine-set static options** (medium). If the material alone does not fix the static key, exact matching
   fails, and the join becomes a nearest-key search that can over- or under-select.
3. **Model-file format 10.4** (medium). Names are 64-bit hashes looked up in `ExternalBinaryString.bfres`. The
   hash function was not identified (CityHash64, FNV-1a, MD5 and SHA-1 truncated to 64 bits all fail on the 455
   names). The hash-to-name pairing is inferred from the layout and is not confirmed.
4. **Passes are chosen at draw time** (certain, but bounded). Materials cannot say which of the 9 passes a draw
   uses. The decoder gives one static key with 9 passes, so about 9 pairs per material (9.3 on average). Shadow
   or translucency flags in render info could narrow this (**assumed**).
5. **Materials outside `Model/`** (low–medium). There are 237 other `.bfres` files, materials created at run
   time, and actors that swap materials. Foliage and terrain are not drawn from `Model/*.bfres` (**assumed**).
6. **A weak test** (certain). The 682 drawn pairs map to 5,263 programs, because programs share code, so a check
   at pair level is easy to pass. Use the 440 drawn pairs that belong to exactly one program as the strict test.

## Evidence

### 1. Real bytes

**`Shader/Model.Product.110.product.Nin_Ounce_NVN2.bfsha`** (320,672,184 bytes unpacked). Verified in hex:

| Field | Value |
| --- | --- |
| Magic | `FSHA    ` |
| Version bytes | `01 01 09 00` (9.1.1) |
| Byte-order mark | `fffe` |
| Relocation table at 0x18 | 0x131d0000 |
| File size at 0x1c | equals the real size |
| Shading-model array at 0x48 | 0x80, records of 0x100 bytes |
| Count | u16 at 0x78 = 2 |

The count is at 0x78. 0x7a holds 0x1a in both files I read, so it is not the count.

| Shading model | Static options | Dynamic options | Programs | Key words (static + dynamic) | BNSH variations |
| --- | ---: | ---: | ---: | --- | ---: |
| `model` | 243 | 5 | 23,346 | 21 + 1 | 23,346 at 0xf7d000 |
| `model_meshlet_taskmesh_override` | 243 | 8 | 1,683 | 21 + 1 | 1,683 at 0x11543000 |
| (MergeShader) `ui` | 55 | 1 | 121 | 4 + 1 | 121 |

Shading-model record fields, **verified** by values that agree across both archives (the sloperina offsets hold
for `Model.Product.110` too):

- +0x00 name
- +0x08 static option array, +0x18 dynamic option array (records of 0x28 bytes)
- +0x88 program array (records of 0x40 bytes, +0x20 = file offset of the BNSH variation)
- +0x90 key table: one row of static words then dynamic words per program, all 23,346 rows distinct
- +0xa8 BNSH
- +0xe4 / +0xe6 / +0xe8 static, dynamic and program counts
- +0xea / +0xeb key words

Option record fields, **verified**:

- +0x00 name
- +0x08 choice dictionary (a Switch-style dictionary: u32 0, u32 count, then 16-byte nodes, name pointer at +8)
- +0x18 choice count
- +0x1a default
- +0x20 mask, +0x24 word, +0x25 shift

The dynamic options' word is 21, right after the static words. Fields not identified: option +0x1c/+0x1e (u16 0,
then 0x0200 for static and 0x1500 for dynamic options), and most pointer pairs of the shading model from +0x28 to
+0x80. Going by the public layout, those are probably attributes, samplers, uniform blocks and storage blocks
with their dictionaries (**recalled from memory**).

Compared with the public Switch BFSHA as I remember it (BfshaLibrary and Switch-Toolbox, versions up to about 8;
**recalled, not checked**): the same idea of static and dynamic options with bit-packed keys and one BNSH per
shading model. What is new here is version 9.1.1, task and mesh slots in the binary program (+0x40, +0x48), and
the program order differing from the BNSH variation order. A public reader for 9.1.1 itself exists only as
sloperina's `uishader.c` (MergeShader, verified to agree).

Dynamic options of `model` (**verified**, choice names read):

| Option | Choices |
| --- | --- |
| `gsys_weight` | `-1`…`8` |
| `gsys_assign_type` | `gsys_assign_material`, `cubemap`, `zonly`, `depthshadow`, `xlu_zprepass`, `visualize`, `dynamic0..3`, `user0` |
| `gsys_index_stream_format` | one choice |
| `foliage_motion_output_enabled` | one choice |
| `system_id` | one choice |

The meshlet model adds three `gsys_meshlet_vertex_attribute_bitmask_*` options. Static option name prefixes:
`ns_` 155, `o_` 81, `gsys_` 7.

Static keys per shading model (**verified**): `model` has 2,218 distinct static keys. 1,976 of them have 9
programs, the rest 18 to 54. Within a key, `gsys_weight` is fixed and `gsys_assign_type` takes 9 values. The
meshlet model has 185 keys of 9 or 18 programs.

**`Model/Land_Deku_Room_A.Land_Deku_Candle_A_01.bfres`** (664,392 bytes):

- **Verified:** magic `FRES    `, version `00 04 0a 00` (10.4). One `FMDL` at 0xf0, two `FMAT` (0x298, 0x348),
  two `FSHP`, two `FVTX`, one `FSKL`, `_STR` at 0x4850, `_RLT` at 0xa2120.
- **Verified:** a shared block at 0x3f0 names shader archive `Model` and shading model `model`. Its dictionaries
  have 35 entries (options), 129 (parameters), 4 (attributes `_p0 _n0 _t0 _u0`), 3 (samplers `_a0 _n0 _rgh0`) and
  17 (render info). The option dictionary's keys are **64-bit values, not string pointers**: an array at 0x2df0
  of 35 (u64 hash, u64 value) records.
- **Verified:** all 35 hashes occur in `ExternalBinaryString.bfres`, which is also an `FRES` 10.4 file.
- **Inferred from the layout, pairing not confirmed:** the external string file holds an array of 454 u64
  hashes at 0xf0 (ascending in the first entries), a dictionary of 454 entries at 0xf20, and `_STR` at 0x2b98
  with 455 names (`ns_` 213, `p_` 106, `o_` 82, `gsys_` 43).
- **Verified:** the material's option choices are local strings (`0`, `1`, `2`, `300`, `10`, …; the array
  starts at 0x2290). Its +0x10 points at 0x2200, whose first pointer is the shared block's name pair.
- **Not identified:** the per-material index arrays (0x1998: u16s of 1; 0x19e0: u16 offsets; 0x1f98 and 0x21b8:
  0xffff fill), how a material overrides the shared values, and whether the 35 shared options are per model or
  per material.
- Compared with public BFRES 5–9 (**recalled**): there each material's ShaderAssign carries its own option
  dictionary with string names. This file instead shares one block per model and stores names as hashes in an
  external file, as Tears of the Kingdom's files do (**recalled**).

### 2. How `varN` is derived today

`nx2_shader_extract.cpp`, `Walker::Walk` → `EmbeddedBnsh` → `Bnsh()`, lines about 411–500 (**verified**, read).
The extractor never parses the FSHA container. It scans any blob for `BNSH\0\0\0\0`, takes the BNSH size at
+0x1c, and walks `grsc` +0x1c/+0x20, the variation array. `varN` is the index `v` in that array, and the label is
`<file>#BNSH@<offset>#var<v>`. Everything outside the BNSH goes unread: the shading-model names, all option
records and choice dictionaries, the key table, and the program array that maps program to variation. So
**none of piece (a) is fields the extractor already walks past.** It skips the whole FSHA header.
`research/shader-extraction/README.md` only notes the shading-model name (+0x00) and BNSH (+0xa8). What
makes (a) cheap is the layout above plus sloperina's reader, not the extractor.

Also **verified:** the program order is not the variation order. Program 0 of `model` uses BNSH variation 2,808,
and 23,319 of 23,346 programs differ from their own index. The map is one-to-one. A decoder must go program →
+0x20 → variation, never assume `varN` = program.

### 3. Validation design

Drawn set D: union over `cache1..3.fork-v54.bin` (`lichii_cache.parse_cache`) of graphics records' (VertexB =
`unique_hashes[1]`, Fragment = `[5]`) pairs, kept if the pair is in `Model.Product.110`'s variations via
`inventory.json` `code_hash`. **Measured: 682 pairs** (`pairs.py`). All 12,574 pairs from that archive are found
in no other file. A second count gives 661 and 12,427; the difference may come from counting mesh pipelines, or
deduplicating by fingerprint rather than `code_hash`. Fix the definition in the validation script and state it
there.

- **Recall, pair level:** D ⊆ output. Expected and required: 682 of 682.
- **Recall, strict:** 440 of the drawn pairs belong to exactly one program (106 to two, 136 to three or more). For
  those 440, the exact program, meaning its static key and its pass, must be in the output. This test can
  actually fail. The pair-level test is soft, because the 682 pairs map to 5,263 programs across 1,885 of the
  2,218 static keys.
- **Precision:** there is no ground truth, since the three sessions visited a small part of the game. Report
  |output|, |output ∩ D|, and the share of output pairs drawn (now 682 of 12,574 = 5.4%). Expect the decoder to
  output about 10,000–12,500 pairs, so about 5–7% (**assumed**). That is low because of what was played, not
  because the decoder is wrong. With pass ranking alone: 10,717 pairs (12,574 − 1,857 `dynamic3`) with 682
  drawn, 6.4% (**measured**). Dropping `dynamic0`, `dynamic1` or `user0` as well would lose 26, 20 and 15 drawn
  pairs, so they stay in, ranked low.
- **Pass mix** (**measured**, pair → its programs' passes):

  | Pass | Pairs | Drawn |
  | --- | ---: | ---: |
  | `dynamic0` | 2,279 | 26 |
  | `xlu_zprepass` | 2,198 | 155 |
  | `material` | 2,184 | 299 |
  | `dynamic3` | 1,857 | 0 |
  | `cubemap` | 1,714 | 89 |
  | `dynamic1` | 1,612 | 20 |
  | `user0` | 421 | 15 |
  | `depthshadow` and/or `zonly` | 288 | 76 |

- **Option check:** report the share of material keys that hit the key table exactly. Below about 95%, step 5
  is not done.

### 4. What the decoder does not cover, by size

Pairs from `nx_pairs.json` grouped by source file family, with drawn = in the three caches (**measured**,
`pairs.py`; a pair is counted in every family that holds it):

| Family | Pairs | Drawn | Decoder covers it? |
| --- | ---: | ---: | --- |
| `Effect/*.vsetb` | 13,987 | 267 | no (effect sets, a different format) |
| `Model.Product.110` | 12,574 | 682 | yes |
| `Lib/agl` `.sharcb` (engine: post-processing, shadows, …) | 4,969 | 68 | no |
| ApplicationPackage `.sharcb` | 1,161 | 29 | no |
| `Lib/Terrain` `.sharcb` | 289 | 2 | no |
| `Layout2Shader` (UI) | 113 | 57 | no (and small) |
| `TerrainGround.Product.110` | 67 | 15 | too small to bother; keep all |
| `Lib/gsys` `.sharcb` | 48 | 1 | no |
| ApplicationPackage `Model` / `TerrainGround` bfsha | 40 / 12 | 0 / 0 | keep all |
| `SceneMaterial.*` | 1 each | 0 | keep all |

- The decoder's scope is about 12,700 of 33,253 pairs (38%) and 697 of 1,121 drawn pairs that appear in the
  tables (62%). Effects are the largest family left out: 42% of pairs, 24% of drawn.
- `Foliage.Product.110` has **no** vertex/pixel pairs. It is mesh-only (it is in `mesh_combos.json`, 1,271
  combinations in all), so the claim "covers terrain/foliage" does not hold in the way it was meant. Terrain is 67
  pairs, foliage needs the mesh path, and foliage materials probably come from `Foliage/` placement data, not
  `Model/` (**assumed**).
- Cutscenes: no separate shader file for them was seen. If their models are `Model/*.bfres`, they are in scope
  (**assumed**).
- Also seen: 1,235 vertex/pixel pairs in the caches, of which 114 are in no extracted table. That is a gap in the
  pairing tables, outside this task.

## What I could not check

- How the hashed option names map to text: the hash function was not identified, and the hash ↔ name pairing in
  `ExternalBinaryString.bfres` was not confirmed.
- How per-material values override the model-wide shader block, and whether a material can change the shading
  model or archive.
- Whether the archive's static keys equal the set used by the game's materials. This is the main open question,
  and TODO step 4 answers it.
- Which static options the engine sets itself.
- Only one model file was read. Other models (skinned characters, translucent props, other folders) may use other
  layouts or other shader archives.
- Nothing about how much faster preparation gets from dropping records. That needs a build and a preparation run,
  not made.
- Public BFSHA and BFRES layouts were recalled from memory, not re-read. No external source was fetched.
