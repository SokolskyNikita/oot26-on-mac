# White specks at the Kokiri cave wall: MoltenVK mesh pipelines never applied cull mode (2026-11-17, fixed)

White specks on the moss and grass at the Kokiri cave wall (and elsewhere native mesh shaders draw foliage), in every
frame there, unless every mesh shader was emulated. The fix is in the pinned build (MoltenVK patch
`patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch`; library `17f76f69f2`, #2901 plus
this fix). Measured on an Apple M4 Pro (Mac16,8) under macOS 27.0.1. Run folders named `ab-<date>-<time>` are local
run data and are not tracked.

## Mechanism

The scene's HDR target is cleared to bright white. Opaque colour is drawn depth-EQUAL with no depth write, against a
depth pre-pass. Wherever the pre-pass wrote grass depth but the grass colour didn't land, the white stays, and bloom
spreads it.

**Cause:** MoltenVK's mesh shader support (PR #2842) nulls a mesh pipeline's input-assembly state, so its topology
stays at point list. The encoder applies cull mode, fill mode and the "cull both faces" discard only for triangle
topologies, so a mesh draw inherited whatever cull mode the previous draw left. The moss colour draws (program
`3e64dc9496175ce8`, MSL `d7cb57fc05f30840`) ran with back-face culling the game never asked for, while their pre-pass
(`a1bc03c341c8279c`) did not. Emulated mesh programs are ordinary triangle pipelines, which hid it.

**Fix** (`MVKPipeline.mm` only; the same patch as `patches/upstream/moltenvk-mesh-cull-mode.patch`): a mesh pipeline
takes its topology from the mesh shader's declared output primitive (`OpExecutionMode` OutputPoints /
OutputLinesEXT / OutputTrianglesEXT) and drops the dynamic PrimitiveTopology / PrimitiveRestartEnable flags.

## Proof

GPU trace replay (`eden-cli --replay`, a 2.2 GB trace recorded in run ab-20261117-221356, deterministic: 40/40
frames at 3.518 % white as recorded), 20 frames each:

| Replay | Speckled | White share |
| --- | --- | --- |
| Cull forced to none at the moss colour draws | 0/20 | 0.000 % |
| Forced back | 20/20 | 3.518 % (identical to the fault) |
| Forced front | 20/20 | 4.064 % |
| Patched MoltenVK, nothing forced | 0/20 | 0.000 % |

Live at the cave wall, 30-frame bursts scored by `tools/speckcheck/whitecount.py` (pixels with R, G, B ≥ 235, HUD
masked, a frame counts above 0.3 %):

| Run | Speckled |
| --- | --- |
| Run that found the fault (run ab-20261117-233936, run data not kept): patched build | 0/30, 0/30 again |
| The same, unfixed build (#2901 test build) | 28/30 |
| Independent check (spec `val-cull`, not kept, a separate build of the patch; `tools/speckcheck/specs/wall-burst.json` repeats the burst on the pinned build): unfixed reference | 27/30 |
| Independent check: patched | 0/30, 0/30 |
| The fix installed in the pinned build (run ab-20261118-000338) | 0/30 |

The 28 and 27 of 30 are two runs of unfixed builds, one from each check. No visible frame cost (standing ~17–19 ms
p50).

## What was ruled out

- **Not** the JIT change, MoltenVK PR #2901, the compiler build, or the CPU backend (a JIT build 23/30, Hypervisor
  30/30).
- **Not** timing: list-indirect off, list check, frames ahead 0, fetch drain, uint8 host path off, GPU split off,
  keep-encoder off, full write marks, async draws wait, UBO reuse off, sync GPU, buffer downloads, read traps off, GPU
  accuracy High: all 24–30/30. Metal API and shader validation clean.
- **Not** precision: position invariant (500+ shaders rewritten) 30/30.
- **Narrowed by:** full mesh emulation 0/40; mesh threadgroup-memory limit ≤21,000 bytes clean, ≥21,300 speckled
  (the limit decided which programs ran natively); the replay was deterministic, so not a CPU/GPU race; pre-pass
  limited to mesh group 0 clean; swapping the depth compare changed the result.
- **Offline negatives** (all still ~3.5 %): buffer marking, zeroed threadgroup memory, no atomics, fast math, four
  subgroup variants, smaller threadgroup memory, constant texture sample, flat-colour fragment, all-buffer
  `useResource`, full rebinds, filled pipeline limits, position-only output, swapped-in pre-pass code, upload watch.
- **Found** by the Metal logger (`mtlspy`) dumping raster state: cull mode 2 on the moss colour draws; cull 0 at all 8
  moss draws with the patch. The draw-by-draw state check ([`tools/statecheck`](../../tools/statecheck/README.md))
  built afterwards reports 263 of 653 mesh draws wrong without the fix and 0 with it.
- Wrong readings corrected on the way: a "turf4 only" conclusion from one screenshot, a shared-counter theory, and
  an early "clean" capture run scored by the first detector version (re-scored 39/40).

## PR #2842 audit (head `b93bdef3e3`)

One fault (the cull bug). Latent gaps not reached by this game: the static sample mask and logic op aren't copied to
the mesh pipeline descriptor (private-API mode only); the draw-index binding bypasses the binding cache; multiview mesh
asks for a pipeline state never built (reported unsupported); the point-size builtin is enabled for mesh shaders.
SPIRV-Cross also doesn't apply reversed-depth viewport and clip/clamp post-transforms to mesh shaders (the moss uses a
plain 0..1 viewport). Recommendation: don't revert the PR; report the cull bug and the first two gaps upstream. The
cull-mode fault was reported on #2842 on 2026-11-18; the patch has not been posted.

## Not done

Untested with the fix: the heavy Kokiri site (x −4.2, z 22.7), Gerudo Valley water streaks, Hyrule Field white tufts
while "Building: 554 shaders" (suspected separate and transient). Tools:
[`tools/speckcheck`](../../tools/speckcheck/README.md).
