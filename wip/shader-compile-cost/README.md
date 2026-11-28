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
| Skip the front end (`makeLibrary(data:)` with ready bitcode) | 196 → 66 ms on a median shader (3.0×), a ceiling | Bitcode written by LLVM 15 is accepted (section 5). No translator from Lichii's IR or SPIR-V to that bitcode exists; DXMT's `airconv` does it from DirectX bytecode |

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

Read out of Apple's binaries (`tools/dumpopts.m`, `tools/dumpstr.m`): 22 properties on `MTLCompileOptions`, among
them the undocumented free-text `additionalCompilerArguments`, and 295 environment-style names
(`data/environment-names.txt`). No explained list of either was found in public. About 2,400 single settings were
tried on a median cached shader with slim classes (baseline rows range ±4%); none but the two in the Answer table
makes a cold compile faster without changing results.

| Group | Tried | Result | Data |
| --- | --- | --- | --- |
| Flag arguments | 919 accepted of 3,015 option strings in the front-end library | 862 within ±4%; the faster ones loosen floating-point rules | `data/argument-sweep.tsv` |
| Value arguments (`name=value`) | 142 real options × 22 generic values, 428 accepted | none faster | `data/value-and-pipeline-sweep.tsv` |
| `-mllvm` pass-through | 4 | ignored: a made-up option name is accepted | – |
| Environment names | 281, each set to 1 and to 0 | none faster; validation and capture switches slower | `data/environment-sweep.tsv` |
| Option properties | 16 | none faster; `tracingEnabled` 45× slower, `debuggingEnabled` +22% | `data/value-and-pipeline-sweep.tsv` |
| `driverCompilerOptions`, `gpuCompilerSPIOptions` on the pipeline descriptor | 171 guessed keys each | no effect on time or code; the real keys are not known | same |
| In-source pragmas and attributes | 30 variants | none within 5%; `optnone` and `noinline` behave like `-O0` and `-fno-inline` | – |
| User-defaults keys, feature flags, forced internal-build gate (client process) | 20 | none faster | – |
| Metal 4 compiler (`MTL4Compiler`, `tools/bench4.swift`) | same shaders, 1 to 64 tasks, its options | equal to the older calls within 2% at every task count | – |

Why most switches do nothing: every `AGC_` name and about a dozen `MTL_` names are read only when
`os_variant_has_internal_diagnostics` is true, in the app and again inside `MTLCompilerService`. `MTLGetEnvDefault`
reads the environment only. `MTLCompilerService` can also read the `com.apple.Metal` preferences domain; the one key
found there that acts on the back end is `UseGlobalISel` (AGXCompilerCore, no gate). It is untested: setting it means
writing the user's `com.apple.Metal` domain, which applies to every Metal app.

Other things these runs showed:

- SPIRV-Cross's lowercase `#pragma metal fp math_mode(safe)` and `#pragma metal fp contract(off)` in the `spvFMul`
  family are reported as unknown pragmas and ignored; the compiler knows only the uppercase `#pragma METAL fp`. The
  helpers stay exact because they call `fma()` and the library is compiled in safe mode.
- A compile runs at the calling thread's priority: from a background-priority thread it is about 6× slower
  (685 ms against 117 ms through `MTL4Compiler`).
- Concurrency stops helping at 14 tasks (`maximumConcurrentCompilationTaskCount`): 64 shaders take 22–23 ms each at
  8 tasks and 17–18 ms at 14.
- `tools/bench.swift` reads each file inside its wall clock (about 17 ms per shader at one thread); its `lib=` and
  `pipe=` figures are not affected.

## 4. Optimisation levels and code size

On a median cached shader with slim classes; GPU code is the fragment program's `__text` size read from a binary
archive (`tools/gpusize.py`). 1,659 of 1,686 settings give the default's 22,306 bytes (`data/gpu-code-size.tsv`).

| Argument | Front end | Back end | Total | GPU code |
| --- | --- | --- | --- | --- |
| none | 56.1 ms | 61.4 ms | 117.5 ms | 22,306 |
| `-disable-lifetime-markers` | 54.0 ms | 58.6 ms | 112.6 ms | 21,260 |
| `-O1 -disable-lifetime-markers` | 50.6 ms | 60.0 ms | 110.6 ms | not measured |
| `-disable-llvm-passes` | 50.5 ms | 71.1 ms | 121.6 ms | 22,454 |
| `-O0 -disable-O0-optnone` | 42.5 ms | 105.0 ms | 147.5 ms | not measured |
| `-O0` | 36.2 ms | 115.4 ms | 151.6 ms | 78,356 |
| fast or relaxed maths (6 spellings) | 54.4 ms | 55.1 ms | 109.5 ms | 19,174 |

The back end redoes the front end's optimisation when it is allowed to (`-disable-llvm-passes`: almost the same
code, slower back end); `-O0` also marks functions as not to be optimised, which is why its code is 3.5× larger. No
quick first build beats the normal build in total time. `-disable-lifetime-markers` is a standard Clang front-end
option; it halves both steps on loop-heavy shaders (1,722 merge nodes → 191 on the regenerated one) and gives a few
percent on typical cached ones. Run-time speed of any variant was not measured.

## 5. Feeding Metal ready-made bitcode

A library cut out of Metal's cache (`libraries.data`) loads with `makeLibrary(data:)` and builds a pipeline with no
front-end work. `tools/repack.py` swaps the bitcode inside such a file: the size fields, a SHA-256 of the bitcode and
the `HDYN` and `RLST` offsets have to be patched.

| Bitcode in the library (median cached shader) | Accepted | Back end | GPU code |
| --- | --- | --- | --- |
| Apple's own | yes | 62–66 ms | 22,306 |
| Disassembled and reassembled by LLVM 15.0.7 | yes | 62–63 ms | 22,306 |
| The same after LLVM 15's `opt -passes='default<O2>'` (target triple removed for `opt`, restored after) | yes | 56 ms | 20,428 |
| Reassembled by LLVM 22 or 23 | no: Apple's bitcode reader aborts | – | – |

Whether the LLVM 15-optimised version computes the same result was not checked. DXMT (`3Shain/dxmt`, LGPL 2.1+,
shipped in CrossOver) builds this bitcode from DirectX bytecode in its `src/airconv` and pins LLVM 15 for it; Apple's
Metal Shader Converter does the same from DXIL. Nothing public does it from SPIR-V.

Compiled GPU programs are Mach-O objects of CPU type `applegpu`, in `functions.data` and in binary archives;
`otool -l` lists their sections.

## Tools

Build the Swift tools with `swiftc -O NAME.swift -o NAME` and `dumpopts.m` with
`clang -fobjc-arc -framework Foundation -framework Metal`. Shader sources are game code: keep them in `local/`.

| File | What it does |
| --- | --- |
| `tools/extract_msl.py` | writes every unique Metal source from a copy of MoltenVK's pipeline cache |
| `tools/bench.swift` | cold compile timing of fragment sources: library and pipeline step, threads (`-j`), language version (`-lang`), extra arguments (`-args`), option properties (`-kv`), pipeline settings (`-pipekv`), a prebuilt library (`-metallib`), a binary archive (`-archive`) |
| `tools/prep_headers.sh`, `tools/slim.py` | the slim texture class generator and the header preparation it needs |
| `tools/dumpopts.m` | lists compile option properties and environment-style names in Apple's Metal libraries |
| `tools/probe.swift`, `tools/sweepargs.sh`, `tools/sweepenv.sh`, `tools/phase2.sh` | which arguments the compiler accepts; timing of each argument, environment name, value argument and pipeline key on one shader; code size of each |
| `tools/gpusize.py` | fragment and vertex GPU code size inside a serialised binary archive (`bench -archive`) |
| `tools/bench4.swift` | the same timing through Metal 4's `MTL4Compiler` |
| `tools/dumppipe.m`, `tools/dumpstr.m` | private pipeline-descriptor settings; every string of the Metal, compiler and driver images |
| `tools/profsum.py`, `tools/profleaf.py` | summarise a `sample` profile of `MTLCompilerService` by pass and by leaf function |
| `tools/repack.py` | swaps the bitcode of a one-function metallib |

## Open

- Slim classes inside SPIRV-Cross or MoltenVK: fix the generator's two failure kinds (an unsubstituted coherence
  parameter in `read`-style methods; `sample_compare` overloads), add the fallback, compare rendered output.
- A translator from Lichii's IR (or SPIR-V) to Apple's bitcode with LLVM 15, using DXMT's `airconv` as the worked
  example for the container and metadata. The ceiling is about 3× on a median shader.
- `UseGlobalISel` in `com.apple.Metal`: set, time, compare code, delete.
- Run-time speed and identical output of the variants that change the code (`-disable-lifetime-markers`, LLVM 15
  `-O2` on the bitcode), with `fsx.swift` from `../shader-metal-analysis/shader-compare/`.
- The `sampler` type's 6 ms per library: it is not a template, so it cannot be specialised the same way.
- Metal 4 pipeline specialisation (`newRenderPipelineStateBySpecialization`) for the 7–9% of fragment programs
  compiled a second time for a blend or format change: not tried.
- A second translator for comparison: `adriadam10/mkw-recomp` goes Nvidia code → GLSL → SPIR-V and checks its decoder
  against Nvidia's `nvdisasm`; its `glsl_cpu.py` runs a translated fragment shader on the CPU for one pixel.
