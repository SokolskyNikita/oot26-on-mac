# The game's Nvidia shaders against their Metal translations

Done 2026-11-17, offline, on an M4 Pro. No emulator was run and no Nvidia hardware was available, so everything about
Nvidia's side is read from the game's code, not measured. Tools are in
[`../shader-compare/`](../shader-compare/); the Lichii sources read are those of
`build/old-trees/path-60/lichii` in the main checkout.

## Answer

- **The translation is faithful instruction for instruction.** One fragment shader compared in detail does the same
  406 multiplies/adds and the same 18 texture samples on both sides, and its arithmetic is bit-exact on Apple's GPU.
- **One rendering difference is real and widespread: the mip level of conditional texture samples.** A third of the
  game's automatic-mip samples (4,723 of 13,682, in 625 of 850 fragment programs) run under a condition that can
  differ between neighbouring pixels. Apple then picks the wrong mip on the pixels where the condition flips. Taking
  the gradients before the branch fixes it exactly and costs nothing (section 3). Not yet looked for in the running
  game.
- **The emulator's guessed buffer sizes are the other rendering risk.** They have already caused two visible Ocarina
  bugs, both fixed (section 4).
- **Speed: three translation artefacts cost time, the rest cost nothing** (section 5).

  | Artefact | Cost on the shader studied |
  | --- | --- |
  | Bit-exact (safe) maths instead of fast-math | 8–22% |
  | Resources passed through an argument buffer | 5–8% |
  | Emulating Nvidia's uniform registers per pixel | 3–8% |
  | Branches, `fma` wrappers, precise min/max, sign flips | none measurable |

- **Smaller gaps exist on paper only** (section 4): centroid interpolation is dropped, a rounding mode is ignored,
  and Apple's `exp2`/`log2` are 1–3 units in the last place off.

## 1. What is compared

The chain from the game's code to what the GPU runs:

1. The game ships compiled Nvidia machine code (Ampere, 16-byte instructions). Lichii's shader cache holds it.
2. Lichii lowers it to its older Maxwell form, translates that to its IR and emits SPIR-V.
3. SPIRV-Cross inside MoltenVK (revision `98cbb7c`) turns the SPIR-V into Metal source.
4. Apple's compiler turns that into AIR bitcode and then GPU machine code. The bitcode can be disassembled with
   LLVM; the final machine code cannot be read.

Three caches hold the three forms, and nothing links them by hash, so pairs are matched by content: the set of
varyings and texture handles for guest ↔ Metal source, and input and sample counts for Metal source ↔ bitcode. The
pair studied is guest program `be9d02075289c06d`, a lit surface shader. A sibling differing in one instruction
confirmed the match.

## 2. Operation counts for one shader

| | Nvidia code | Metal bitcode |
| --- | --- | --- |
| Instructions | 631 | 1,774 (1,014 without bookkeeping) |
| Multiply / add / fused multiply-add | 406 | 405 `fma` calls |
| Texture samples | 18 | 18 |
| Conditional execution | 70 predicated instructions in 33 runs, 1 real branch | 71 conditional branches in 148 blocks |

- Nvidia predicates single instructions; Metal has no equivalent, so each predicated run becomes an `if`.
- Every guest multiply and add becomes a call to a helper that wraps `fma`, so Apple's compiler cannot reorder or
  fuse them. The helpers are needed: without them about 20% of `x*y+z` expressions were silently fused (measured on
  1M inputs).
- The extra Metal instructions are loads through the argument buffer, bit-casts, and the emulation of uniform
  registers (section 5).

## 3. The mip level of conditional samples

**What the game does.** A sample with automatic mip selection needs the texture coordinates of the neighbouring
pixels in its 2×2 quad. On Nvidia the coordinates sit in registers that every pixel holds, whether or not that
pixel executes the sample. (Read from the code's structure; not verified on hardware.)

**What the translation does.** The sample is emitted inside an `if`. Metal leaves the mip undefined when the
neighbours do not take the same branch, and the recompiler does nothing about it.

**How common it is** (data-flow scan of all 850 fragment programs, `mipflow.py`):

| Automatic-mip samples | Count |
| --- | --- |
| Total | 13,682 |
| Unconditional | 8,099 |
| Conditional, condition the same across a quad | 852 |
| Conditional, condition can differ per pixel | 4,723 (290 predicated, 4,433 inside a branch) |
| Conditional, not classified | 8 |

On the Metal side, 697 of 944 cached fragment shaders have such a sample nested in a block, which agrees.

**What Apple does** (measured, `mipfix.swift`, on cached shader `msl/0625` = guest `566f86aa1ac2ddb3`, which samples
two textures only where a third texture's value is zero). The test textures hold their own mip level, so the output
shows which level each pixel got:

| Variant | Pixels with the wrong mip | Time, 8 passes at 1080p |
| --- | --- | --- |
| As MoltenVK emits it | 12,384 (35% of pixels in quads where the condition differs), about 9 levels off | 0.333 ms |
| Samples hoisted out of the branch (reference) | 0 | 0.485 ms |
| Gradients taken before the branch, samples still conditional | 0, bit-identical to the reference | 0.331 ms |

- The wrong pixels get the smallest mip: a one- or two-pixel fringe of blurred texture along the edge of the
  condition.
- The fix is to compute `dfdx`/`dfdy` of the coordinates where control flow is still uniform and pass them to the
  sample. It is exact and free here. In the recompiler it means hoisting the derivative, not the sample.

**Limits.** The scan says a condition *can* differ per pixel, not how often it does. The shader studied in section 2
is not affected: its conditional samples depend only on per-draw values.

## 4. Other rendering differences

| Difference | Where it comes from | Visible? |
| --- | --- | --- |
| Buffer size guessed for global-memory reads | The game's pointers have no size. `buffer_cache.h:4414-4450` guesses one and only that span holds game data | Has been: grass culled at an 8 MiB cap, fog overbright at 64 MiB. Both fixed by larger caps |
| Centroid interpolation dropped | `load_store_attribute.cpp:152` declares `sample_mode` and never reads it; inherited from yuzu, unreported upstream | Not while MSAA is off, as in all 2,493 cached pipelines |
| Round-toward-zero ignored | 15,792 multiplies carry a rounding field the decoder reads as toward-zero; the SPIR-V backend never looks at it | At most one unit in the last place each; 102 feed a float-to-integer conversion |
| `exp2` / `log2` accuracy | Apple's GPU implementation: 79% / 49% correctly rounded, worst 2 / 3 units. Every Metal variant returns the same bits | No |
| Sign of zero from min/max | Unspecified in SPIR-V and Metal | No |

Checked and found equal:

- **Arithmetic:** `fma(x, y, -0)` equals `x*y` and `fma(1, x, y)` equals `x+y` bit for bit, except on denormals.
- **Denormals:** the game requests flush-to-zero on every float operation in fragment and vertex programs (84 fused
  multiply-adds in 9 compute programs excepted), and Apple flushes natively.
- **NaN:** min/max return the non-NaN operand and saturate gives 0, as the translation assumes.
- **sqrt, rsqrt, 1/x:** correctly rounded in safe mode.
- **Bindless textures:** the three handle registers of the studied shader map to three Metal textures in the same
  pattern. Whether the right texture is bound per draw needs a run.

Out-of-range buffer reads on Apple (measured, `oob.swift`): past the bound range but inside the same Metal buffer
they return that buffer's contents; past the end of the buffer they returned zero. MoltenVK writes only an address
into the argument buffer, so the Vulkan range is never enforced.

## 5. Performance

All times are GPU time for 8 blended full-screen passes at 1080p of the shader from section 2, with synthetic
inputs. One pass is about 0.44 ms. Every safe-maths variant below produced bit-identical pixels.

| Change | Effect |
| --- | --- |
| Fast-math, shader as generated | 8–10% faster; up to 5% of pixels change, by at most 0.03% |
| Fast-math plus all artefacts removed | about 22% faster; up to half the pixels change, by at most 0.05% |
| Direct bindings in place of the argument buffer | 5–8% faster (noise about ±2%) |
| Uniform-register emulation removed | 3–8% faster |
| Branches flattened to selects | 4–6% slower |
| `fma` wrappers, precise min/max, sign flips, layer round-trip removed | no change |
| Texture samples replaced by a constant | 35% faster |

- **Fast-math** is what a native Metal shader would use. The emulator cannot, because it has to reproduce each
  Nvidia instruction exactly. Earlier tests agree (see `research/allinone-frame-breakdown/`); a whole-game run was spoiled
  by App Nap and never repeated.
- **Argument buffers.** Direct binding fits 742 of 944 cached fragment shaders, all 684 vertex shaders and 152 of
  157 compute shaders. The rest exceed Metal's 16 samplers (178 fragment shaders carry a 64-sampler array) or 31
  buffers. A small shader showed no gain.
- **Uniform registers.** Nvidia keeps some values once per group of pixels. Where the game copies a per-pixel
  register into one, every pixel in the group must see one pixel's value, which the emulator does with
  `simd_ballot` and `simd_shuffle`. It is correct, not a bug. Only 154 of 631 fragment programs use such copies
  (645 in all); 191 of them are provably the same for every pixel and could skip the shuffle, 222 are genuinely
  per-pixel, 232 could not be classified. (Counted on a cache copy from 2026-11-16.)
- **Textures.** With compressed, mipmapped 2048² textures the texture share stays at 35–43%. Uncompressed textures
  raise it to 50–63%, 8× anisotropic filtering or missing mips to as much as 78%. Coordinates that jump between
  neighbouring quads make the shader 10–20× slower. Whether the game's coordinates do is not known.
- **Overdraw.** Eight overlapping opaque draws cost the same as one: Apple shades each opaque pixel once.

## Open

- **Look for the mip fringe in the running game**, and build the gradient fix into the recompiler if it shows.
- **Run-time bindings:** which texture each bindless handle resolves to, and whether any global-memory read lands
  outside its guessed binding.
- **Real frame cost:** whether the per-shader percentages show up in frame time, and a clean whole-game fast-math
  run.
- **Nvidia's side:** maths-function accuracy, what the rounding bits and the min/max zero-sign case really do, and
  how much Nvidia saves by doing uniform work once per group. All need Nvidia hardware.
