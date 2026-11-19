# Every shader in the game, and which mesh shaders overflow Metal's threadgroup limit

Done 2026-11-16, offline, from a dump of the game: one `.nup` file holding the base game and the update (section
1). No emulator was run. The scripts (`extractor/shaders/`) and their output (`dump-out/shaders/`, 642 MB of game
code) belong to the separate glitch-research repository this one grew out of; they are not in this repository, and
the output is game data that must not be published.

## Answer

- **The game ships 440 mesh shaders in the set version 1.1.1 loads, plus 9 in the engine's AGL archive: 449.**
  289 of them are in the `.110` shader archives, 151 in the package's default archives, 9 in `AglShader.sharcb`.
  Mesh shaders exist nowhere else in the romfs (every file was scanned).
- **10 are predicted over 32,768 bytes, all in `Shader/Foliage.Product.110`**: 4 that Lichii has already compiled
  (the known 42,012 / 35,100 / 35,100 / 34,076) and 6 that it has not. The largest unseen one is predicted at 48,412
  bytes. The size rule reproduces all three known sizes exactly.
- Lichii's cache holds 51 mesh programs (53 distinct codes after splitting on the SPH), all found in the
  extracted set. The other 387 live mesh shaders have not been run in Lichii.

| Set | Mesh codes | In Lichii's cache | Predicted over 32,768 |
| --- | --- | --- | --- |
| `Foliage.Product.110` (14 shading models) | 49 | 26 | **10** |
| `Model.Product.110` (`model_meshlet_*_override`) | 238 | 27 | 0 (max 28,388) |
| `ApplicationPackage` SARC's own `Foliage` / `Model` bfsha | 51 + 102 | 0 | 0 (max 8,732) |
| `AglShader.sharcb` (engine) | 9 | 3 | 0 (max 9,500) |
| `.100` archives (not loaded by 1.1.1, see below) | 336 more | 0 | 14 |

## 1. Where the shaders are

`Shader/` holds the game's shaders; `ootx get` unpacks them (zstd):

| File | Format | Holds |
| --- | --- | --- |
| `Shader/{Foliage,Model,SceneMaterial,TerrainGround}.Product.{100,110}.product.Nin_Ounce_NVN2.bfsha.zs` | BFSHA 9.1.1 | game shaders; `.110` is the set 1.1.1 uses |
| `Shader/ApplicationPackage.Nin_Ounce_NVN2.release.sarc.zs` | SARC | 4 small default bfsha, `AglShader.sharcb`, `FoliageShader.sharcb`, AAMP configs |
| `Layout2Shader/MergeShader.Product.100.Nin_Ounce_NVN2.bfsha.zs` | BFSHA | UI shaders (only a `.100` exists) |
| `Lib/{agl,gsys,Terrain}/*_resource.Nin_Ounce_NVN2.release.sarc.zs` | SARC of `.sharcb` | engine shaders (vertex, fragment, compute) |
| `Effect/*.Nin_Ounce_NVN2.vsetb.byml.zs` (~1,400 files) | effect sets | vertex, fragment, compute only; not extracted |

### Which package each file comes from

The dump is a single `.nup` file whose name ends in `[0400486024DEC000][v131072]`. The `v131072` names its newest
package, but the file holds two: the base game (title `0400486024DEC000`, version
65536) and the update (title `0400486024DEC800`, version 131072). Both report display version 1.1.1. `ootx` lays the
update over the base, as the emulators do, and every extraction here read that combined view. Comparing the
packages' own records (size and sha256, no unpacking) gives this provenance:

| File | Base | Update | What the game runs |
| --- | --- | --- | --- |
| `Shader/*.Product.110.product.*.bfsha` (4 files) | absent | present | update (only copy) |
| `Shader/*.Product.100.product.*.bfsha` (4 files) | present | absent | base copy; not loaded (below) |
| `Shader/ApplicationPackage…sarc` | present | present, **different** | update's copy (extracted) |
| `Lib/agl/agl_resource…sarc` | present | present, **different** | update's copy (extracted) |
| `Lib/gsys/…`, `Lib/Terrain/…`, `Layout2Shader/MergeShader…`, `Shader/ExternalBinaryString.bfres` | present | present, identical | either |

So every shader counted as live in this write-up comes from the update package or from files the two packages share
byte for byte. The `.100` bfsha exist only in the base. The base's own ApplicationPackage and agl SARCs are replaced
by the update and were not extracted. Across the whole romfs the update repeats 185,774 of the base's 185,999 files,
184,303 of them identical; it adds 814 files.

How this was found: Lichii's cache (`~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin`, format in Lichii
`src/video_core/shader_cache_v2/`) stores each program's guest instructions. 64 bytes from each cached mesh and
task program were searched for in the unpacked `Shader/` files; every one was found in a `.110` bfsha or in the SARC.

The glitch-research repository's `scan_romfs.py` then read all 186,808 romfs files (SARC members included) and counted
NVN control blocks by stage. Mesh and task controls occur only in `Shader/Foliage.*`, `Shader/Model.*` and the
`ApplicationPackage` SARC, so no map, pack or effect file carries its own mesh shaders. Effects carry about 33,500
vertex/fragment/compute controls and `Movie/*.dat` 22.

### The container, as read here

Worked out from the data. Offsets are from the start of each structure; BNSH pointers are already relocated to
offsets from the BNSH start.

- **BFSHA** (`FSHA    `, version bytes `01 01 09 00`). One shading-model record of 0x100 bytes per model from 0x80:
  +0x00 pointer to its name (u16 length + text), +0xa8 pointer to its BNSH. Foliage has 14 models (`moss`,
  `ornament_impostor`, `low_tree_shootleaf_impostor`, `low_tree_impostor`, `flower`, `stone`, `turf4`, `turf1`, `leaf`,
  `forest`, `stalk`, `blade`, `frost`, `leaf_near`). Every BNSH's own file name is `dummy`.
- **BNSH** (`BNSH\0\0\0\0`, +0x1c u32 size, +0x16 u16 offset of `grsc`). `grsc` +0x1c u32 variation count,
  +0x20 u64 variation array (0x40 bytes each; +0x10 binary program).
- **Binary program**: +0x08 + 8·slot = pointer to a ShaderCode, slots 0..9. Slots seen: 0 vertex, 4 fragment,
  7 task, 8 mesh.
- **ShaderCode**: +0x08 control, +0x10 code, +0x18 u32 code size, +0x1c u32 control size.
- **Code**: a 0x80-byte shader program header (SPH), then 16-byte Ampere instructions. Lichii's cached instructions
  are `code[0x80 : 0x80 + 16·n]` byte for byte.
- **Control** (NVN's program control, magic `34 12 76 98`, then `c9`): +0x56 u16 stage (0 vertex, 1 fragment,
  5 compute, 6 task, 7 mesh). For mesh: +0x58 u16 threads (32 in every mesh shader), +0x60 u16 max vertices,
  +0x62 u16 max primitives; +0x5f is 3 for all but two (likely the topology). One control is shared by every code that
  has the same one, so counting controls undercounts codes.
- **AGL `.sharcb`** (`BAHS`, version 11): +0x18 u32 code region size, +0x1c u32 code region offset. Each code is
  named by a 16-byte record: u32 offset into the code region, u32 0, u32 control size, s32 offset from the record to
  its control. Code size is at control +0x44. Compute codes have no SPH (Lichii's `header_size` 0).

## 2. Extraction and inventory

In the glitch-research repository, from its root:

```bash
extractor/shaders/extract_all.sh
```

It unpacks the containers (to `$TMPDIR/oot-shader-containers`, or a folder given as the argument), runs
`bnsh_extract.py` and `sharcb_extract.py`, then `report.py`, in about 15 s. It reads Lichii's cache and does not change
it. Output in `dump-out/shaders/`:

| Path | Contents |
| --- | --- |
| `live/` | the BNSH set 1.1.1 uses (`.110` bfsha, the SARC's bfsha, MergeShader): `codes.json` and `code/<sha>.<stage>.bin` |
| `agl/` | the `.sharcb` codes (ApplicationPackage and Lib SARCs) |
| `v100/` | the `.100` bfsha; codes already in `live/` are counted there |
| `mesh.json` | one row per mesh code: V, P, threads, SPH output lines, vec4 outputs, estimated bytes, Lichii ids, shading model |
| `cache_match.json` | Lichii unique hash → extracted code(s) |
| `mesh_report.txt` | the summary and the over-limit list |

The romfs scan is separate (about 40 s): run
`uv run --with numpy --with zstandard python -I shaders/scan_romfs.py ../game.nup OUT.json` inside `extractor/`.

Distinct codes, deduplicated by SHA-1 of the code bytes:

| Set | Vertex | Fragment | Compute | Task | Mesh |
| --- | --- | --- | --- | --- | --- |
| live BNSH | 2,581 | 9,352 | — | 11 | 440 |
| AGL `.sharcb` | 638 | 5,524 | 469 | 3 | 9 |
| only in the `.100` archives | 2,685 | 9,223 | — | 4 | 336 |

Two codes can share all their instructions and differ only in the SPH output map (bytes 0x36–0x3c); they are
different shaders to Lichii and to Metal, so they count separately.

**The `.100` archives are not used by 1.1.1.** They come from the base package; the update ships `.110` archives
alongside them instead of replacing them by name. Almost all of their code differs from `.110` (they were recompiled), and
none of the 1,325 programs in Lichii's cache matches anything that exists only in `.100`.

## 3. Check against Lichii

Lichii's cache was matched against the extraction by instruction bytes (`report.py`):

| Stage | Cached programs found / not found |
| --- | --- |
| mesh | 51 / 0 |
| task | 3 / 0 |
| vertex | 360 / 147 |
| fragment | 511 / 117 |
| compute | 66 / 70 |

All mesh and task programs are accounted for. The unmatched vertex/fragment/compute programs are most likely effect
shaders (`.vsetb`), whose container was not decoded; that is not checked.

**Shader ids.** Lichii's id for a program (`unique_hash`) is CityHash64 of its *lowered* code XOR `0x4f554e4345000002`
(`NativeShaderHash`, `src/video_core/native_lowering.cpp`). The lowering is Lichii's own C++, so the id can't be
computed offline for a shader Lichii has not run. For the 56 cached mesh codes the ids come from the cache and are in
`mesh.json`.

**The three known ids are not Lichii's.** `f745a892263a512e`, `efdc2d865aa74afe` and `aad4571246c8d55c` occur nowhere in
Lichii's cache files or logs, in either byte order or as text. MoltenVK names its `MVK_CONFIG_SHADER_DUMP_DIR` files
`shader-ms-<codeHash>.metal`, where `codeHash` is its hash of the SPIR-V, so these are almost certainly MoltenVK ids.
Without that dump they were matched by size:

| Known (MoltenVK) | Bytes | Cached code with that predicted size | Lichii id | Shading model |
| --- | --- | --- | --- | --- |
| `f745a892263a512e` | 42,012 | `596bf62483f9ce1e` (only one) | `2ec1079a33205f7d` | Foliage `flower` |
| `efdc2d865aa74afe` | 35,100 | `fbb731e2f95b52fa` or `cc777b7a335964d4` | `1e22f77149e2dfc9` / `f5fb15be43839a9b` | `leaf` / `leaf_near` |
| `aad4571246c8d55c` | 34,076 | `4095357147c1f19d` (only one) | `c15b4ff4c4952968` | Foliage `stalk` |

Two cached shaders come out at 35,100. Which of them is `efdc2d865aa74afe` is not known.

The Lichii id here is the program's `unique_hash`. Lichii's logs and pipeline keys use a different value for mesh
and task stages: `unique_hash` XOR `MeshStateHash()` (`shader_cache.cpp:291`, read). That most likely explains why
[mesh-fallback](../mesh-fallback/README.md) names the same `aad4571246c8d55c` shader `d395e5a0ccbe218f`.

## 4. Threadgroup size

### What determines it

Lichii's SPIR-V for a native mesh shader (`EmitContext::DefineMesh`, `spirv_emit_context.cpp`) declares in workgroup
memory:

- `isbe_attributes`: u32 × (⌈V/32⌉ · vertex_lines · 32 + ⌈P/32⌉ · primitive_lines · 32)
- `isbe_map`: u32 × (4 + 3P) for triangles
- `isbe_primitive_count`: one u32

Its outputs are `gl_Position` float4[V] plus one float4[V] per generic location the shader writes. SPIRV-Cross stages
the outputs, and the triangle indices, in threadgroup memory too.

| Input | Where it is read |
| --- | --- |
| V (max vertices), P (max primitives), threads | control +0x60, +0x62, +0x58. In the game Lichii gets these from GPU registers NVN sets from the same data. |
| vertex_lines | SPH: set bits of `omap_systemb` (0x35) plus component bits of `omap_generic_vector` (0x36–0x45), as Lichii's `AddMeshLines` counts them |
| vec4 outputs | generic locations with any component set, plus 1 for position |

The (V, P, lines) combinations decoded for the 56 cached codes are the same set Lichii's "Mesh emulation survey" log
lines print for its pipelines. That confirms the decoding.

### The rule

```
bytes = 128·⌈V/32⌉·lines + 16·V·vec4_outputs + 28·P + 28
```

The first two terms come from the declarations. `28·P + 28` was fitted: `isbe_map` (16 + 12P), the count (4), uint3
triangle indices (16P) and 8 bytes not accounted for.

| Known size | V | P | lines | vec4 outputs | Predicted |
| --- | --- | --- | --- | --- | --- |
| 42,012 | 160 | 128 | 24 | 9 | 42,012 |
| 35,100 | 128 | 64 | 25 | 10 | 35,100 |
| 34,076 | 128 | 64 | 23 | 10 | 34,076 |

The fit has two unknowns (per-primitive bytes and a constant) and three points; the two P = 64 shaders agree on the
same constant. The other 52 cached codes are predicted under the limit, as Metal found for the 53 dumped shaders.
The rule has not been reconciled with the per-part predictor in
[mesh-fallback](../mesh-fallback/README.md).

### Predicted over the limit (version 1.1.1)

| Code (sha1 prefix) | Shading model | V | P | lines | vec4 | Bytes | In Lichii's cache |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `7289a62f246f6b3c` | Foliage `flower` | 160 | 128 | 26 | 11 | **48,412** | no |
| `596bf62483f9ce1e` | Foliage `flower` | 160 | 128 | 24 | 9 | 42,012 | `2ec1079a33205f7d` |
| `fbb731e2f95b52fa` | Foliage `leaf` | 128 | 64 | 25 | 10 | 35,100 | `1e22f77149e2dfc9` |
| `0a46d30b9f6ae21e` | Foliage `leaf` | 128 | 64 | 25 | 10 | 35,100 | no |
| `f2d25847d06453cb` | Foliage `forest` | 128 | 64 | 25 | 10 | 35,100 | no |
| `32e44244a92bfb55` | Foliage `forest` | 128 | 64 | 25 | 10 | 35,100 | no |
| `cc777b7a335964d4` | Foliage `leaf_near` | 128 | 64 | 25 | 10 | 35,100 | `f5fb15be43839a9b` |
| `d3079f157cfef61a` | Foliage `leaf_near` | 128 | 64 | 25 | 10 | 35,100 | no |
| `4095357147c1f19d` | Foliage `stalk` | 128 | 64 | 23 | 10 | 34,076 | `c15b4ff4c4952968` |
| `5a5714c3a853673a` | Foliage `stalk` | 128 | 64 | 23 | 10 | 34,076 | no |

The two `flower` shaders also break Metal's other limit, threadgroup plus mesh output ≤ 61,440 (from `tg_audit2.py` of
[mesh-threadgroup-memory](../mesh-threadgroup-memory/README.md)): 76,572 and 65,052. No mesh shader's output alone
exceeds 32,768.

The nearest shaders under the limit are three impostor shaders at 30,620 (Foliage `ornament_impostor`,
`low_tree_impostor`, `low_tree_shootleaf_impostor`; not cached), then `stone` at 30,364. Model shaders peak at 28,388.

### Where the unseen ones are probably drawn

Not established; this is a pointer only. Both `forest` shaders are unseen, and Kokiri Forest has no `Forest` foliage
placement. `Foliage/Placement/Scene/<area>/<map>.<map>.Forest.flnt` exists for Death Mountain Trail, Graveyard, Hyrule
Castle, Hyrule Field, Kakariko, Zora's Fountain and Zora's River (adult and child). That the `Forest` placement type
draws with the `forest` shading model is a guess from the names. The other unseen ones are further variations of
`flower`, `leaf`, `leaf_near` and `stalk`, models Kokiri Forest already uses. Which material options select them was
not decoded.

### How reliable

- **Exact on all 53 mesh shaders of a fresh dump.** It was fitted on three calibration shaders;
  [mesh-threadgroup-memory](../mesh-threadgroup-memory/README.md) checked it against all 53 sizes in a
  `MVK_CONFIG_SHADER_DUMP_DIR` dump and it reproduces every one.
- **Per-primitive outputs are ignored.** Lichii takes them from a separate pass-through geometry header that was not
  located in the data. Its logs show one pipeline with 4 per-primitive lines, a V=128, P=64, 6-line shader. For
  P = 64 that adds about 1 KB per 4 lines plus 1 KB per per-primitive vec4. That is not enough to move the 30,620
  shaders over unless they have several.
- **It depends on Lichii and SPIRV-Cross.** The rule fits the build measured on 2026-11-16 (Lichii `7c7f723` /
  CI `960f215`, MoltenVK main + #2842 + #2843, SPIRV-Cross #2686). Source was read from the fallback build's Lichii at
  `1f76c9ff5`. A change to how Lichii lays out `isbe_*`, or to SPIRV-Cross staging, changes the numbers.
- **The margin is clear on both sides.** The smallest predicted overflow is 34,076 (+1,308) and the largest predicted
  pass is 30,620 (−2,148). An error of a few hundred bytes would not change the list.

## 5. Not done

- **Lichii ids for the 387 unseen live mesh shaders.** This needs Lichii's native lowering: a small tool built from
  Lichii's source, or a run of the emulator.
- **A forced build of the six unseen oversized shaders**, to confirm the list beyond the 53 that a dump reaches.
- **Which variation is which**: the BFSHA option tables (option name → value per variation) and the link from
  foliage materials and placements to shading models and variations. With these the unseen shaders could be tied to
  maps.
- **The effect container** (`.vsetb`) and `Movie/*.dat`. Their vertex, fragment and compute shaders were counted by
  control block, not extracted. This probably explains Lichii's ~330 unmatched cached programs.
- **The source of per-primitive outputs** (Lichii's `MeshPrimitiveHeader`).
