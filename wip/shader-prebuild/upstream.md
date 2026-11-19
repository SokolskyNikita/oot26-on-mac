# Upstream: what was posted

All of these were posted from the user's GitHub account on 2026-11-17. The texts are on GitHub and are not repeated
here. Replies were last checked on 2026-11-17 (evening); none had arrived.

| Where | What it says | Waiting for |
| --- | --- | --- |
| [zortos293/Lichii PR #1366, comment](https://github.com/zortos293/Lichii/pull/1366#issuecomment-6964687495) | The PR's precompiled pipelines run on MoltenVK with the four Mac changes in [README.md](README.md); the first-visit results; Metal's 1 GiB cap means the full file does not stay prepared | the maintainer's view on the Mac state model and on taking the changes |
| [KhronosGroup/MoltenVK#2907](https://github.com/KhronosGroup/MoltenVK/issues/2907) | Stack overflow in SPIRV-Cross `CFG::walk_from` on a secondary thread, because macOS gives threads 512 KiB stacks (Lichii now uses 256 MiB for its shader workers) | triage |
| [sharpemu/sharpemu-mac#50](https://github.com/sharpemu/sharpemu-mac/issues/50) | Their 3 GiB `MTL_SHADER_CACHE_SIZE` is clamped to 1 GiB, with the disassembly and our measurements | their answer |
| [dttdrv/mullion#171, comment](https://github.com/dttdrv/mullion/issues/171#issuecomment-6964688685) | The same clamp, and that their binary-archive route is the way past it | — |
| [KhronosGroup/MoltenVK#1765, comment](https://github.com/KhronosGroup/MoltenVK/issues/1765#issuecomment-6964689098) | Binary-archive probe results, including that an archive file opens as an `MTLLibrary` | interest in a patch ([binary-archives.md](binary-archives.md)) |
| [zortos293/Lichii PR #1970, comment](https://github.com/zortos293/Lichii/pull/1970#issuecomment-6966678494) | Reply to HyperCed on the mesh-shader fallback rule. It has the per-shader size table for all 440 mesh programs (also in [../mesh-threadgroup-memory/mesh-shader-sizes.csv](../../research/mesh-threadgroup-memory/mesh-shader-sizes.csv)) and a correction: 53 of the 56 reached shaders are in the 440, and 48 of them are demoted. It ends by asking whether they will run the rule-only A/B themselves | **their answer**. If they want our numbers, it is about 1–2 h with the emulator: one variant build and several runs at the Kokiri Forest spawn |

Not posted, on purpose: the MSL dumps behind the size table, because they are translated game shader code.
