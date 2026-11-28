# Where a cold shader compile spends its time, and what can be cut

Measured offline on 2026-11-27 (Apple M4 Pro, macOS 27.2, GPUCompiler 32023), on the Metal sources held in MoltenVK's
pipeline cache for Ocarina (2,816 unique sources, 1,408 of them fragment shaders). No emulator run is involved: every
number is a cold compile through `MTLDevice` with Metal's disk cache off (`MTL_SHADER_CACHE_SIZE=0`). Nothing here is
in MoltenVK, Lichii or the pinned build.

## Answer

| Change | Serial gain on real cached fragment shaders | State |
| --- | --- | --- |
| Slim texture classes (section 2) | 258.6 → 147.8 ms per shader on 64 shaders (1.75×); front end alone 2.5× | Offline prototype. Bitcode identical on the one shader compared. 62 of 2,816 sources fail the quick generator |
| `-disable-lifetime-markers` on top (section 4) | 147.8 → 138.4 ms (6%) | Offline. Output not compared |
| Compile as Metal language 3.0 instead of 4.0 | 1.48× on 64 shaders; 1 of 2,816 sources fails | Alternative to slim classes, weaker. Generating at 3.0 instead would bring back un-inlinable helpers (SPIRV-Cross PR 2721) |
| 8 compile threads | 5.7× alone, 8.8–11.5× with the above | Metal scales; blocked in MoltenVK by the picture corruption seen with concurrent compiles (TRACKER) |
| Skip the front end (`makeLibrary(data:)` with ready bitcode) | 196 → 66 ms on a median shader (3.0×), a ceiling | Bitcode written by stock LLVM 22 and 23 is rejected by Apple's reader; no writer exists |

A serial 2× from compile changes alone was not reached. Best measured: 1.87×.

## 1. Where the time goes

One median fragment shader (1,427 guest instructions) through every stage, 311 ms:

| Stage | Time | Share |
| --- | --- | --- |
| Lichii: Nvidia code → SPIR-V | 3.6 ms | 1.2% |
| SPIRV-Cross: SPIR-V → Metal source | 7.0 ms | 2.3% |
| Apple front end: source → bitcode | 193.3 ms | 62.2% |
| Apple back end: bitcode → GPU code | 107.1 ms | 34.4% |

That shader was regenerated offline (`shader-sweep --guess-missing`, then SPIRV-Cross's own CLI) and has 7 loops; cached
shaders average 1. Its proportions are a fair picture, but loop-related costs are overstated. The cached shaders'
means on a 64-shader sample are 187 ms front end and 71 ms back end.

Inside the front end, for that shader: texture class instantiation 95.6 ms, optimisation passes ~60 ms (instruction
combining ~26 ms, loop-invariant code motion ~9 ms), preamble 11 ms (the `sampler` type alone 6.2 ms), parsing the
body 11 ms, code generation and link ~12 ms. Inside the back end: machine-code passes ~63 ms (register allocation
~20 ms), instruction combining again ~10 ms, lowering ~10 ms.

Front-end time over all 1,404 slimmed fragment shaders is linear in source lines (R² 0.92; no squared term) and is
carried by the computing statements; the copy-and-declare boilerplate from Lichii's register model costs about nothing.

## 2. The texture class cost

Mentioning a texture type makes Apple's compiler instantiate every member of the class. The classes repeat each
method per address space, and newer language versions add more.

| Metal language | Member functions in `texture2d` | Cost of mentioning it once |
| --- | --- | --- |
| 2.0 | 63 | 6 ms |
| 3.0 | 207 | 12.5 ms |
| 4.0 | 409 | 41 ms |

The cost is per distinct type per library. A shader can instead declare its own explicit specialisation, for example
`template <> struct texture2d<float, access::sample, memory_coherence_threadgroup, void>`, holding the builtin handle
(`__metal_texture_2d_t t;`) and only the methods it calls. The compiler accepts it as a texture in argument buffers
and entry points. `tools/slim.py` writes these, copying the method bodies from Apple's headers. It needs
`#pragma METAL internals : enable` and a friend trick to read `sampler`'s private handle, so it depends on Apple's
internal names and needs a fallback to the plain source on a compile error.

## 3. Compile options and switches

Read out of Apple's binaries (`tools/dumpopts.m`): 22 properties on `MTLCompileOptions`, among them the undocumented
free-text `additionalCompilerArguments`, and 295 environment-style names (`data/environment-names.txt`). No explained
list of either was found in public.

- 919 of 3,015 option strings from the front-end library are accepted (`data/accepted-arguments.txt`); 458 more take a
  value and were not tried with one.
- All 919 were timed on a median cached shader (`data/argument-sweep.tsv`; baseline rows range ±4%). 862 are within
  ±4%. The only ones faster by more loosen floating-point rules (`-frelaxed-math`, `-freciprocal-math`).
- 13 environment switches tried one at a time (among them `AGC_DISABLE_OPTIMIZATIONS`, `AGX_FORCE_OPTSIZE`,
  `MTL_MONOLITHIC_COMPILER`) changed nothing.

## 4. Optimisation levels

On a median cached shader with slim classes:

| Argument | Front end | Back end | Total |
| --- | --- | --- | --- |
| none | 56.1 ms | 61.4 ms | 117.5 ms |
| `-O1 -disable-lifetime-markers` | 50.6 ms | 60.0 ms | 110.6 ms |
| `-O0 -disable-O0-optnone` | 42.5 ms | 105.0 ms | 147.5 ms |
| `-O0` | 36.2 ms | 115.4 ms | 151.6 ms |

Skipping front-end optimisation makes the back end slower by more than it saves, and the GPU code larger (31.6 KB →
75 KB on the regenerated shader). A quick first build followed by an optimised one therefore has no quick build to
start from. `-disable-lifetime-markers` halves both steps on loop-heavy shaders (1,722 merge nodes → 191 on the
regenerated one) and gives about 6% on typical cached ones.

## 5. Feeding Metal ready-made bitcode

A library cut out of Metal's cache (`libraries.data`) loads with `makeLibrary(data:)` and builds a pipeline with no
front-end work. `tools/repack.py` swaps the bitcode inside such a file: the size fields, a SHA-256 of the bitcode and
the `HDYN` and `RLST` offsets have to be patched. Bitcode reassembled by stock LLVM 22 or 23 loads but aborts in
Apple's bitcode reader when the pipeline is built.

Compiled GPU programs are Mach-O objects of CPU type `applegpu` in `functions.data`; `otool -l` lists their sections.

## Tools

Build the Swift tools with `swiftc -O NAME.swift -o NAME` and `dumpopts.m` with
`clang -fobjc-arc -framework Foundation -framework Metal`. Shader sources are game code: keep them in `local/`.

| File | What it does |
| --- | --- |
| `tools/extract_msl.py` | writes every unique Metal source from a copy of MoltenVK's pipeline cache |
| `tools/bench.swift` | cold compile timing of fragment sources: library and pipeline step, threads (`-j`), language version (`-lang`), extra arguments (`-args`), a prebuilt library (`-metallib`) |
| `tools/prep_headers.sh`, `tools/slim.py` | the slim texture class generator and the header preparation it needs |
| `tools/dumpopts.m` | lists compile option properties and environment-style names in Apple's Metal libraries |
| `tools/probe.swift`, `tools/sweepargs.sh` | which arguments the compiler accepts; timing of each on one shader |
| `tools/profsum.py`, `tools/profleaf.py` | summarise a `sample` profile of `MTLCompilerService` by pass and by leaf function |
| `tools/repack.py` | swaps the bitcode of a one-function metallib |

## Open

- Slim classes inside SPIRV-Cross or MoltenVK: fix the generator's two failure kinds (an unsubstituted coherence
  parameter in `read`-style methods; `sample_compare` overloads), add the fallback, compare rendered output.
- The `sampler` type's 6 ms per library: it is not a template, so it cannot be specialised the same way.
- A bitcode writer Apple's reader accepts (an LLVM closer to Apple's version), then whether Lichii's IR can be written
  as bitcode directly.
- Apple's own per-phase timers (`MTL_WRITE_COMPILE_STATS_TO_JSON_FILE`, `AGC_ENABLE_STATUS_FILE_TIMING`), the private
  pipeline settings (`gpuCompilerSPIOptions`, `driverCompilerOptions`) and the arguments that take a value: not tried.
