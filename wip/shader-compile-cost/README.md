# Where a cold shader compile spends its time, and what can be cut

Measured on 2026-11-27 (Apple M4 Pro, macOS 27.2, GPUCompiler 32023), mostly offline on the Metal sources held in
MoltenVK's pipeline cache for Ocarina (2,816 unique sources, 1,408 of them fragment shaders): every offline number
is a cold compile through `MTLDevice` with Metal's disk cache off (`MTL_SHADER_CACHE_SIZE=0`). Slim texture classes
(section 2) are in the pinned build as MoltenVK patch 0012; nothing else here is.

## Answer

| Change | Serial gain on real cached fragment shaders | State |
| --- | --- | --- |
| Slim texture classes (section 2) | 258.6 → 147.8 ms per shader on 64 shaders (1.75×); front end alone 2.5×. In the game: cold boot 95.7 → 70.0 s | In the pinned build (patch 0012). GPU code byte-identical for all 2,816 sources |
| `-disable-lifetime-markers` on top (sections 4, 6) | 147.8 → 138.4 ms (6%) | Tested in the game behind a switch: walk median 3.5% better, pictures clean; not adopted (under the 5% bar) |
| Compile as Metal language 3.0 instead of 4.0 | 1.48× on 64 shaders; 1 of 2,816 sources fails | Alternative to slim classes, weaker. Generating at 3.0 instead would bring back un-inlinable helpers (SPIRV-Cross PR 2721) |
| 8 compile threads | 5.7× alone, 8.8–11.5× with the above; scaling stops at 14 tasks | Metal gives byte-identical GPU code serially and at 8, 14 and 32 at once, so the picture corruption seen with concurrent compiles (TRACKER) is in MoltenVK or Lichii |
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
and entry points.

MoltenVK's `MVKSlimTextureClasses` (patch 0012) does this just before a library is compiled:

- It reads the method bodies from the standard library headers installed with the compiler
  (`GPUCompiler.framework/Versions/Current/.../include/metal`), with a small evaluator for the `#if defined(...)`
  lines and `metal_config`, so the bodies are the ones the compiler would have used. It declares `T`, `a`, `c` and
  `__derived_t` inside the specialisation, so the bodies are copied unchanged except for `s.val`, which is private
  to the library's own classes and is read through a specialisation of a class `sampler` befriends.
- It covers `texture2d`, `texture3d`, `texture2d_array`, `texturecube` and, where `spvDepthCast` is called, `depth2d`,
  `depth2d_array` and `depthcube`, for `float` with sample access, from MSL 3.2.
- It costs 0.25 ms per source and 9 ms once for the headers. The MSL stored in the pipeline cache is not changed.
- A library that does not compile with the specialisations is compiled as generated, and the first failure is
  logged. `MVK_P60_NO_SLIM_TEXTURES=1` turns the pass off.

Checked on all 2,816 cached sources: each compiles, and the GPU code (`__TEXT,__text` of the stage's object in a
binary archive) is byte-identical with and without the pass: fragment 1,408, vertex 1,026, compute 253, mesh 116
(with and without an object stage), object 8, other fragment 5. In the game, same app with the switch as control,
two alternating pairs of cold boots: 95.1 and 96.2 s without, 70.0 and 70.1 s with; 6,555–6,608 compiles in every
run; pictures and cube check clean; no library fell back. `tools/slim.py` is the first prototype of the pass.

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
| User-defaults keys, feature flags, forced internal-build gate (client process); `UseGlobalISel` in the service | 21 | none faster | – |
| Metal 4 compiler (`MTL4Compiler`, `tools/bench4.swift`) | same shaders, 1 to 64 tasks, its options | equal to the older calls within 2% at every task count | – |

Why most switches do nothing: every `AGC_` name and about a dozen `MTL_` names are read only when
`os_variant_has_internal_diagnostics` is true, in the app and again inside `MTLCompilerService`. `MTLGetEnvDefault`
reads the environment only. Forcing that check inside the client process, together with the in-process compiler
(`USE_MONOLITHIC_COMPILER=1`, confirmed to run `AGCLLVMCtx::compile` inside the client), still leaves
`AGC_DISABLE_OPTIMIZATIONS`, `AGX_FORCE_OPTSIZE` and the inlining switches without effect; that mode is 6 ms slower.

What selects the back end's passes, read from this machine's AGXCompilerCore, MTLCompiler and libLLVM with IDA:

| Input | Origin | Reachable |
| --- | --- | --- |
| Code-generation level | a literal `CodeGenOpt::Default` when the two target machines are made; `setOptLevel` has no callers | no |
| IR passes (about a fifth of the back end) | one flag, set from `AGC_DISABLE_OPTIMIZATIONS` | internal builds only |
| Machine passes (about half) | `addPassesToEmitFile`, always | no |
| Instruction selector | preference `UseGlobalISel` in `com.apple.Metal`, read in the service without a gate | yes: 1 and 2 change nothing (GlobalISel is the default on this GPU), 3 makes every pipeline fail with "Can't initialize backend" |
| LLVM `cl::opt`s | static defaults; the service never parses a command line | no |

`driverCompilerOptions` is read by the driver in the client: `maxNumRegisters`, `disableTextureRWBoundsCheck`,
`agx_enable_stack_shadow`, `agx_{fragment,vertex,object,mesh}_forward_progress_mode`, and `agx_disable_licm` (compute
pipelines only). None changes time or code size of a render pipeline; `agx_disable_licm` changes a compute
pipeline's code but not its compile time (253 compute shaders: 129.5 against 134.0 ms mean). `gpuCompilerSPIOptions`
has twelve keys, all shader-validation features.

Other things these runs showed:

- SPIRV-Cross's lowercase `#pragma metal fp math_mode(safe)` and `#pragma metal fp contract(off)` in the `spvFMul`
  family are reported as unknown pragmas and ignored; the compiler knows only the uppercase `#pragma METAL fp`. The
  helpers stay exact because they call `fma()` and the library is compiled in safe mode.
- A compile runs at the calling thread's priority: from a background-priority thread it is about 6× slower
  (685 ms against 117 ms through `MTL4Compiler`).
- Concurrency stops helping at 14 tasks (`maximumConcurrentCompilationTaskCount`): 64 shaders take 22–23 ms each at
  8 tasks and 17–18 ms at 14.
- Lichii's shader threads run at the lowest thread priority, but MoltenVK dispatches every compile to the default
  global queue (`MVKSync.mm`), and default QoS compiles as fast as user-interactive.
- Metal 4 specialisation: an unspecialised pipeline costs one back-end compile (65–70 ms on a median shader) and each
  blend or colour-format variant made from it with `newRenderPipelineStateBySpecialization` 0–1.5 ms, against
  60–64 ms each as full pipelines. Whether the remaining work moves to first draw was not checked.
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

## 6. Run-time effect of the variants that change the code

Rendered as full-screen passes with identical synthetic inputs and compared bit for bit (a harness kept only in the
session's scratch folder; it saturates the GPU, so it was stopped after these):

| Variant | Loop-heavy regenerated shader | Median cached shader (one data set) |
| --- | --- | --- |
| Slim texture classes (control) | identical, same time | identical, same time |
| `-disable-lifetime-markers` | identical pixels, GPU time −74% | identical pixels, GPU time −6% |
| Bitcode re-optimised by LLVM 15 | 981 pixels differ (up to 0.024), GPU time −78% | identical on that data set, −10% |

LLVM 15's optimiser does not know what Apple's builtins mean, and its output is not safe as it is.

`-disable-lifetime-markers` over every cached source, with slim classes (GPU code against the default):

| Stage | Sources | Changed | GPU code of the changed ones | Median | Largest gain |
| --- | --- | --- | --- | --- | --- |
| Fragment | 1,408 | 905 | −4.8% | −4.2% | −29% |
| Vertex | 1,026 | 9 | −0.4% | −0.1% | −1% |
| Compute | 253 | 35 | −2.4% | −1.0% | −29% |
| Mesh | 116 | 0 | – | – | – |
| Object | 8 | 7 | −6.7% | −2.4% | −19% |

Seven sources came out larger, by at most 0.7%. In the game (`MVK_P60_NO_LIFETIME_MARKERS=1` against the same
library without it, two alternating pairs on a warm cache, 900-frame walk and 600-frame stand in Kokiri Forest):
walk median 17.84 and 18.23 ms without, 17.49 and 17.33 ms with; walk p95 22.67 and 23.52 against 22.68 and
22.31 ms; standing 16.5–16.7 ms in all four, which is the 60 fps cap; pictures clean. A 3.5% better walk median is
under the pinned build's 5% bar, so the switch is not in it.

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
| `tools/cmpgpu.py`, `tools/cmparch.py`, `tools/cmpstage.py`, `tools/stages.swift` | compare the GPU code inside binary archives of two builds, per stage; build vertex, compute, mesh and object pipelines into archives |
| `tools/cbench.swift`, `tools/spec.swift` | compute pipeline timing with `agx_disable_licm`; Metal 4 specialisation timing |
| `tools/gpusize.py` | fragment and vertex GPU code size inside a serialised binary archive (`bench -archive`) |
| `tools/bench4.swift` | the same timing through Metal 4's `MTL4Compiler` |
| `tools/dumppipe.m`, `tools/dumpstr.m` | private pipeline-descriptor settings; every string of the Metal, compiler and driver images |
| `tools/profsum.py`, `tools/profleaf.py` | summarise a `sample` profile of `MTLCompilerService` by pass and by leaf function |
| `tools/repack.py` | swaps the bitcode of a one-function metallib |

## Open

- Declaring SPIRV-Cross's temporaries at function scope, which should have the same effect as
  `-disable-lifetime-markers` without a private property: not tried. The option itself is worth another look in a
  heavier scene than Kokiri Forest, where standing is not at the frame cap.
- The race behind the picture corruption with concurrent compiles: Metal is cleared, so a thread-sanitizer build of
  MoltenVK replaying a parallel cache load is the next step. Serial against concurrent GPU code was compared for
  fragment shaders only.
- A translator from Lichii's IR (or SPIR-V) to Apple's bitcode with LLVM 15, using DXMT's `airconv` as the worked
  example for the container and metadata. The ceiling is about 3× on a median shader.
- The `sampler` type's 6 ms per library: it is not a template, so it cannot be specialised the same way.
- Metal 4 specialisation for the 7–9% of fragment programs compiled a second time for a blend or format change:
  needs pipelines built through `MTL4Compiler`.
- A second translator for comparison: `adriadam10/mkw-recomp` goes Nvidia code → GLSL → SPIR-V and checks its decoder
  against Nvidia's `nvdisasm`; its `glsl_cpu.py` runs a translated fragment shader on the CPU for one pixel.
- A precompiled header for the texture classes: the runtime compiler accepts `-include-pch` but cannot be made to
  write one; Apple's offline Metal compiler would be needed.
- Not tried: `launchctl setenv` for the ungated `LLVM_*` names in the service; arguments whose value is a separate
  word; combinations of arguments.
