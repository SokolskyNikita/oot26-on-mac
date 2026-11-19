# Rendering faults in Lichii on the Mac: catalogue and playbook

For when the picture is wrong (not slow). Part 1 is the order to work in. Part 2 lists every fault found so far,
so a new one can be matched against them. Part 3 is the switches and tools. Paths are relative to the repository
root; `path-60` is `build/old-trees/path-60`.

Written 2026-11-17 from the local write-ups and the sessions of 2026-11-15 to 2026-11-17. The white specks at the
Kokiri cave wall (section 2.2) were open at the time of writing; the JIT cache session owns their root cause.

## 1. Playbook: a new rendering fault

Work down the list. Each step is one or two harness runs of about two minutes.

### Step 1: pin it down so a run can score it

1. **Where and when.** Note Link's position from the watches box, the save, and whether it shows while standing
   still or only while the view moves. Steady-when-still means a fixed per-pixel fault; only-when-moving or
   frame-to-frame noise means timing or uninitialised data.
2. **Make the harness stand there.** A spec's walk ends at a repeatable spot: the 600-frame bounce walk from the
   Kokiri spawn save ends at the cave wall (x 21.3, y 109.9, z 14.2).
3. **Record and score it at that spot** with the spec key `at_end` (`tools/speckcheck/speckhunt.py`):
   `"at_end": [{"burst": 30, "name": "wall"}]`. The harness reads Link's position from memory until he has stood
   still for 20 frames, stores where he stands, then takes 30 captures of the window. Each burst leaves the frames,
   `sheet.png` (every frame, small), `burst.gif` and a verdict (specks, clean or mixed) in the run folder, so nobody
   has to watch the run. `speck_report.py RUNS_DIR` prints one line per run. Check `at_end.stand.from_wall_m`
   before trusting a burst: a run that stopped somewhere else proves nothing. `"walk_shots": true` adds a capture
   after every chunk of the walk, but it changes the walk (Link ended 9 m short of the wall with it), so use it
   only in a run of its own.
4. **Capture from the window, not with the debug server's `screenshot`.** That call makes the emulator render the
   frame in step, and 1 to 6 frames in 30 came out clean because of it. `flicker` and `capture` also run at the
   spawn, before the walk, so they say nothing about the end spot.
5. **Judge a run by its burst count, never by one frame.** About 1 frame in 30 comes out clean even in an
   affected run. One such screenshot put a bisect boundary in the wrong place for an hour (2026-11-17).
6. **Check the score against eyes once.** `whitecount.py` counts clipped-white pixels and its mask is tuned for the
   cave wall: 2.6–3.4 % of the scene with specks on window captures, 0.000 % clean. Open `sheet.png` once to confirm
   the verdict means what it says. For another fault, write another metric before trusting counts.

### Step 2: which layer (three runs)

| Run | Switch | If the fault goes away |
| --- | --- | --- |
| All mesh shaders emulated | `EDEN_NX2_FORCE_MESH_FALLBACK=1` | Native mesh path (section 2.1 family). Go to step 3a |
| Other CPU backend | `cpu_backend` 2 (Hypervisor) with the render fix, or back to the JIT | CPU/GPU memory tracking. Go to step 3b |
| Synchronised frame capture | `capture_frame` (sampled) in `at_end` | Either pacing matters, or the capture path draws differently. Does not prove a race by itself |

Also run the same spot on one other build (`app-practice`, `app-mvkp2901`, a `build/release` app). A fault on every
build is not caused by the newest patch.

### Step 3a: native mesh path

0. **State inherited from the previous draw: check this first.** Log the raster state Metal actually has at the
   faulty draw (cull mode, fill mode, depth state, winding) and compare it with what the emulator asked for. The
   white specks took an evening of shader work and were a cull mode left over from an earlier draw. A fault that is
   the same in every frame and every boot, and that disappears when the draw goes through another pipeline type,
   points here.

1. **Is it an old fault that an app lacks the fix for?** Check the library's `pipelineCacheUUID` in a run's
   `stderr.log` (it starts with the MoltenVK commit, `8FC3C2AF` = position fixup present) and the
   `[mvk-diag] mesh position fixup added` lines. The subgroup fix and the Y flip / depth fixup exist only in the
   path-60 MoltenVK.
2. **Which programs.** `reject_shaders` per group at the spot (`at_end` step `reject_each`) until the fault's
   geometry disappears. Then compare native against emulated for those hashes:
   `emulator/mvk-mesh/shader-diff/pairdiff.py`.
3. **Depth-equal passes.** The grass is drawn with a depth-equal test against a pre-pass. If the two shaders
   compute position differently, fragments fail the test and whatever is underneath shows through as holes
   (SPIRV-Cross issue 2156). Test with `MVK_CONFIG_FAST_MATH_ENABLED=0` and `MVK_DIAG_INVARIANT`.
4. **Uninitialised outputs.** SPIRV-Cross's Metal mesh shaders keep per-primitive outputs (cull flag, indices) in
   threadgroup memory that is never initialised. This predicts noise from frame to frame even while standing still.
   `EDEN_NX2_UNDEF_ZERO`, and `build/old-trees/tg_audit.py` on a shader dump.
5. **Provoking vertex.** The practice app logs "Device doesn't support feature provokingVertexLast". Flat and
   per-primitive outputs then come from the wrong vertex. Untested.

### Step 3b: memory tracking

1. Log whether the Hypervisor fault handler drops protection on a cached page
   (`wip/hypervisor/patches/01-count-dropped-protection.patch`).
2. Mark pages before protecting them (`02-mark-before-protect.patch`).
3. Read traps and reactive flushing: `EDEN_NX2_READ_TRAPS=0`, GPU accuracy High. `EDEN_NX2_NO_REACTIVE=1` itself
   breaks colours, so it is not a clean test.

### Step 4: record it

Add a row to section 2 with the symptom in the words used on screen, the switch that isolates it, and the run
folders. Faults were rediscovered here under new names ("shards", "flakes", "flashing", "specks") because the
earlier write-ups were not found by name.

## 2. Catalogue

### 2.1 Native mesh shader family (correct with `EDEN_NX2_FORCE_MESH_FALLBACK=1`)

| Seen as | Cause | Status | Fix | Write-up |
| --- | --- | --- | --- | --- |
| Foliage missing | 4–10 mesh shaders exceed Metal's 32,768-byte threadgroup memory | Confirmed | Size-based fallback, Lichii commit `9537add`; `EDEN_NX2_MESH_TG_LIMIT` | `research/mesh-fallback/`, `mesh-threadgroup-memory/` |
| Canopy as flat white or multicoloured shards, white haze, white leaf flakes | MoltenVK reports no subgroup support for mesh and task stages, so all 32 lanes build the same element | Confirmed | path-60 MoltenVK commit `431a3566` | `research/mesh-native-colours/README.md` |
| Leftover white shards, foliage upside down, ground grass missing | No Y flip or depth fixup for a mesh shader's position (SPIRV-Cross issue 2717) | Confirmed | Position fixup, path-60 MoltenVK `8fc3c2af` | `research/mac-performance/README.md` section 4 |
| Stray triangles from vertices the shader never wrote | The NaN guard ran only on the emulated path | Read from code; no visible effect measured | Lichii `44532bbe15` | `mesh-native-colours` sections 5–6 |
| Shards in the canopy, one run in three | An older shader translation in a shared cache file | Suspected | Give each build its own pipeline cache | `mac-performance`, "How to measure" |
| Grass flashing | `provokingVertexLast` not reported by MoltenVK | Suspected, untested | — | `wip/shader-prebuild/README.md` |
| White specks on foliage | MoltenVK does not apply a mesh pipeline's cull mode; the draw inherits the previous draw's | Proven in a replay | In progress (mesh topology from the shader's output mode) | section 2.2 |

### 2.2 White specks on foliage (cause found 2026-11-17, fix in progress in the JIT cache session)

**Cause, proven in an offline replay:** MoltenVK never applies the cull mode of a mesh pipeline. Its pipeline
constructor drops the input-assembly state for mesh pipelines, so the pipeline's primitive type stays "point", and
the encoder only sets cull mode and fill mode for triangle types. A native mesh draw therefore runs with whatever
cull mode the previous draw left. The moss colour draws came after a back-face-culled draw and lost their
back-facing blades; the depth pre-pass happened to follow cull-none draws and was right. Forcing the cull mode at
only the moss colour draws: none 0 of 20 frames speckled, back 20 of 20 (identical to the fault). An emulated mesh
program is an ordinary triangle pipeline, which is why emulating it hid the fault.

**Fix being made:** a mesh pipeline takes its topology from the mesh shader's output primitive mode
(`MVKPipeline.mm`). Details and tools (`mtlspy` Metal call logger, `replay.sh`): `tools/speckcheck/`,
`research/mesh-white-specks/`.

The notes below are the investigation as it went; several leads in them (depth arithmetic, counters, buffer
ordering, SIMD operations, group numbering) were measured and ruled out.


- **Seen as:** pure-white, blade-shaped specks on grass and slopes, spread by bloom, at x 21.3, y 109.9, z 14.2.
  Steady while Link stands still, flickering while the view moves (the owner's observation).
- **Not only at the wall** (owner's screenshots of the 3,600-frame walk, 2026-11-17): also at x 13.2, z 27.6 and,
  much more heavily, by the wooden frame at x -4.2, y 111.7, z 22.7, where most of the ground in view is covered.
  The wall stays the scored test spot; check a fix on a long walk too.
- **Every setup tried at the wall is affected** (`wall-*` runs, window bursts of 30): unpatched JIT 23, JIT with
  mark-before-protect 27, Hypervisor with the render fix 30, ThinLTO JIT 29. So not the build, the CPU backend or
  memory tracking.
- **Bisected by program size, not yet to one program** (recorder bursts, 2026-11-17): clean with native mesh
  programs up to 20,000 bytes of threadgroup memory (0 of 30 at limits 1, 12,000 and 20,000), speckled from 22,000
  up (29 of 30). So the fault needs a native program between 20,000 and 22,000 bytes: `3e64dc9496175ce8` (moss or
  turf1, drawn in the colour pass at the wall), `e237e3fbe30adee9`, `649d4b265a77cec1`, `3e22421d43f25de5`,
  `efeb82dcdfab2e69`, `d1fa5ec040c0bb2b`, `8a2ca5a024029ee3` and six more. turf4 (`717b82304a8d8db5`, 22,172 bytes)
  is **not** needed: it was named first because one screenshot of the limit-22,000 run happened to be a clean
  frame, while that run's burst was 29 of 30 speckled.
- **Reproduces** on every boot tried (15 of 15): practice app, practice Lichii with the PR 2901 MoltenVK, the
  shared-JIT build with its cache on and off. 80–98 % of burst frames.
- **Goes away** with every mesh shader emulated (0 of 40 frames).
- **A sampled `capture_frame` there is clean** in every pass, on a run whose bursts before and after were affected.
  One pass has an HDR-white area where the slope is and the next covers it with grass, so the specks are holes in
  natively drawn grass.
- **No effect:** `P60_LIST_INDIRECT=0`, `EDEN_NX2_LIST_INDIRECT_CHECK=1` (0 lists differ),
  `EDEN_NX2_FRAMES_AHEAD=0`, `EDEN_NX2_FETCH_DRAIN=1`.
- **What the white is** (JIT cache session, capture `tools/harness/runs/ab-20261117-210551/specks-capture`): the HDR scene target
  is cleared to a bright value, a depth pre-pass writes grass depth, and opaque colour is then drawn depth-equal.
  Terrain cannot write where the pre-pass depth is grass, so a pixel whose grass colour draw does not land keeps
  the clear value. Rule: **white on foliage = the pre-pass wrote depth there and the colour draw did not land.**
  Specks are some blades; a flat white tuft is all of them.
- **A second, transient cause of the same picture:** with `native_async_draws` Bounded (the default) a draw is
  dropped while its pipeline builds, which also gives pre-pass depth without colour. Hyrule Field showed every tuft
  white with 554 shaders still building. Judge only after the status bar's build counter has reached zero, or with
  `native_async_draws` set to Wait. At the cave wall Wait did not remove the steady specks (26 of 30).
- **Candidates:** the depth-equal pass failing against its pre-pass (fits steady-when-still), uninitialised
  per-primitive outputs (predicts frame-to-frame noise), the provoking vertex.
- **Runs:** `tools/harness/runs/ab-20261117-210551` (capture, all-emulated) and `-211019` (switch matrix).
  Specs and tools: `tools/speckcheck/specs/`.

### 2.3 Other faults

| Seen as | Where | Cause | Status | Fix | Write-up |
| --- | --- | --- | --- | --- | --- |
| Tree canopy missing, holes in the sky | Stock MoltenVK | `maxPushDescriptors` 287 gives 37-buffer sets; 5 compute pipelines fail, including foliage culling | Confirmed | Cap at 16 | `research/compute-buffer-bounds/README.md` |
| Dark band, missing HUD, watches box jumping | Hypervisor CPU backend | The fault handler makes a page writable between the GPU thread protecting it and marking it cached; the GPU keeps stale data | Confirmed in the log (25 hits in 2.5 min; 0 with the fix) | `02-mark-before-protect.patch` | `wip/hypervisor/render-bug-writeup.md` |
| Fog washed out to near-white, faded colours | `EDEN_NX2_NO_REACTIVE=1` | Reads of GPU-written memory see stale data | Seen on screen | Keep reactive flushing on | `research/emulator-options/README.md`, batch 4 |
| Grass culled, fog overbright | Global-memory size guess | Caps of 8 MiB and 64 MiB too small | Fixed | Larger caps | `wip/shader-metal-analysis/guest-vs-metal-shaders` section 4 |
| 1–2 px wrong-mip fringe | Conditional texture samples on Apple GPUs | Measured offline, not seen in game | Open | Gradient-hoist prototype | same, section 3 |
| INF/NaN in vertex interpolant `out_attr10` | Native and emulated alike | Not tied to mesh shaders | Open | — | `research/metal-validation/` section 3 |
| Picture differs between runs of the same build | Fast math | MoltenVK's fast math changes shader output (16 of 40 runs, up to 19 % of pixels) | Measured | Compare builds with the same fast-math setting | `mesh-native-colours` |

## 3. Switches and tools

### Switches, by layer

| Layer | Switches |
| --- | --- |
| Mesh shaders | `EDEN_NX2_FORCE_MESH_FALLBACK` (all emulated), `EDEN_NX2_MESH_NATIVE_ALWAYS`, `EDEN_NX2_MESH_TG_LIMIT=<bytes>`, `EDEN_NX2_NO_MESH`, `EDEN_NX2_REJECT` / `_REJECT_HASH`, `EDEN_NX2_FORCE_LOD0`, `EDEN_NX2_UNDEF_ZERO` |
| Compute lists | `P60_LIST_INDIRECT=0`, `EDEN_NX2_LIST_INDIRECT_CHECK`, `EDEN_NX2_LIST_MACRO_VERIFY`, `EDEN_NX2_CMDPAGE_DRAIN`, `EDEN_NX2_LIVE_READ_CHECK`, `P60_UINT8_HOST=0`, `P60_HMMA_MEM=0` |
| GPU thread split | `EDEN_NX2_SPLIT=0/1`, `_SPLIT_VERIFY`, `_SPLIT_CHECK`, `EDEN_NX2_FETCH_DRAIN`, `EDEN_NX2_DRAIN_CHECK`, `EDEN_NX2_FRAMES_AHEAD`, `EDEN_NX2_SKIP_SAME=0`, `EDEN_NX2_INLINE_DEFER=0`, `EDEN_NX2_MME_JIT=0` |
| Memory tracking | `EDEN_NX2_READ_TRAPS=0`, `EDEN_NX2_NO_REACTIVE=1`, `EDEN_NX2_BUFFER_DOWNLOADS`, `EDEN_NX2_READ_CHECK`, `EDEN_NX2_UBO_KEEP_VERIFY`, `EDEN_NX2_TEXTURE_MEMO_VERIFY`; config: GPU accuracy High; CPU backend |
| MoltenVK and Metal | `MVK_CONFIG_FAST_MATH_ENABLED`, `MVK_DIAG_INVARIANT`, `MVK_DIAG_NO_OPTNONE`, `MVK_ALLINONE_NO_MESH_FLIP`, `MVK_P60_NO_KEEP_ENCODER`, `MVK_CONFIG_SHADER_DUMP_DIR`, `MTL_DEBUG_LAYER`, `MTL_SHADER_VALIDATION` (with `MTL_SHADER_VALIDATION_RESOURCE_USAGE=0`, or it crashes) |

The full list with defaults is `path-60/lichii/dist/nx2_switches.txt`. A changed MoltenVK option or library makes
the next boot compile shaders cold; with the PR 2901 library (`path-60/app-mvkp2901`) that costs about a minute.

### Tools

| Tool | Use |
| --- | --- |
| `tools/harness/ab.py` | The run harness. Spec keys for pictures: `at_end` (at the end of the walk), `walk_shots` (during it), `flicker` and `capture` (at the spawn) |
| `tools/speckcheck/speckhunt.py` | The `at_end` steps: `burst`, `call`, `frames`, `reject_each` |
| `tools/speckcheck/speck_report.py RUNS_DIR` | One verdict line per run that has an `at_end` burst |
| `tools/speckcheck/whitecount.py PNG_OR_DIR` | Share of clipped-white pixels outside the HUD; flags frames over 0.3 % |
| `tools/harness/dbg.py` | Debug-server calls: `capture_frame`, `capture_bundle`, `screenshot`, `reject_shaders`, `trace_record` |
| `tools/verify/verify.py compare REF CAND` | Tile difference between two screenshots |
| `emulator/mvk-mesh/shader-diff/pairdiff.py NATIVE_DUMP EMU_DUMP` | Native against emulated shader source |
| `build/old-trees/tg_audit.py DUMP` | Threadgroup memory use of mesh shaders |
| `emulator/mvk-mesh/metal-validation/run_to_spawn.sh` | A run under Metal's validation layers |
| `wip/hypervisor/scripts/hvf-interp-test/run.sh` | The Hypervisor store interpreter against the Mac's own CPU |
