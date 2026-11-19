# Comparing guest shaders with their Metal translations

Tools behind [`../guest-vs-metal-shaders/`](../guest-vs-metal-shaders/README.md).
All offline: none of them starts the emulator. The shader dumps they read and write are game code; keep them in a
scratch folder and do not commit them.

## Inputs

| Input | Where |
| --- | --- |
| Guest programs (Nvidia code) | `~/.cache/lichii/shader/0400486024dec000/lichii-cache.v2.bin`, read with `../../../extractor/shaders/lichii_cache.py` |
| Metal source | `vulkan_pipelines.fork-v54.bin` in the same folder (MoltenVK's pipeline cache, plain-text MSL) |
| Metal bitcode | Apple's cache, `$(getconf DARWIN_USER_CACHE_DIR)/io.github.zortos293.lichii/com.apple.metal/*/libraries.data` |
| Prepared standalone shader | a folder written by `build/old-trees/offline-probes/perf/fsprep.py` (main checkout): `fs.metal`, `vs.metal`, `meta.json` |

Lichii rewrites its caches when it runs or precompiles. Copy the cache before a long scan; the scan scripts take the
cache path as their first argument.

## Reading and matching

| Tool | What it does |
| --- | --- |
| `gdis.py NATIVE` | Lists an Ampere program: mnemonic, operand form, predicate, modifiers. Also the decoder the scans import |
| `mtlb.py` | Splits Apple's `libraries.data` into metallibs and indexes their functions |
| `sig.py`, `match.py` | Signatures for guest programs, Metal sources and bitcode, and the content match between them |
| `cfg.py LL` | Branch inventory of one function in disassembled bitcode. Remove the `target` lines first: LLVM does not know `air64_v29` |

## Scans over every cached program

| Tool | Question |
| --- | --- |
| `flow.py` | Backward data flow shared by the scans: is a register or predicate the same for every pixel, per-pixel, or unknown |
| `mipflow.py [CACHE]` | Which automatic-mip samples run under a per-pixel condition |
| `r2ur.py [CACHE]` | Which uniform-register copies are provably the same for every pixel |
| `ftz.py [CACHE]` | Flush-to-zero and rounding bits on float instructions |
| `rz.py [CACHE]` | Where the non-default rounding modes occur and what consumes them |
| `bindlimits.py DIR` | Which Metal sources (`DIR/msl/*.metal`) fit Metal's direct-binding limits |

## GPU harnesses and probes

Build each with `swiftc -O NAME.swift -o NAME`. Shaders are compiled at run time, so no Xcode is needed.

| Tool | What it does |
| --- | --- |
| `mkvar.py DIR` | Variants of a prepared shader, one translation artefact removed in each |
| `fsx.swift` | `fsx DIR name:math[:draws[:blend]] ...`: times full-screen 1080p passes and bit-compares each variant with the first, over 8 synthetic data sets. `summ.py` summarises |
| `mkdirect.py`, `fsxd.swift`, `runab.sh`, `abs.py` | The same shader with every resource bound directly, timed against the argument-buffer form |
| `mkvar2.py`, `fsx2.swift`, `summ2.py` | Texture configurations (size, mips, anisotropy, BC7, ASTC) and coordinate patterns |
| `mkmipfix.py MSL OUTDIR`, `mipfix.swift` | The mip fix prototype: as generated, samples hoisted, gradients hoisted. Run `mipfix` from `OUTDIR` |
| `mathprobe.swift` | Exactness of the `fma` helpers, sqrt, rsqrt, 1/x, min/max, NaN and denormal handling |
| `explog.swift` | Accuracy of every `exp2` and `log2` variant |
| `derivprobe.swift` | Mip selection for samples inside uniform, per-quad and per-pixel branches |
| `oob.swift` | What out-of-range buffer reads return, directly bound and through an argument buffer |

## Things that go wrong

- Timings are noisy when anything else uses the GPU. The harnesses take the minimum of many runs; interleave the
  variants and repeat.
- A float16 render target hides one-unit differences. The harnesses use `rgba32Float`.
- Cached MSL ends with a few bytes of cache data after the final `}`; trim them before compiling.
- Apple's compiler merges identical samples, so a probe needs a different coordinate for each sample it wants kept.
