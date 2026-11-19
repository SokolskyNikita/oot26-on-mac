# compile-time: where a shader compile spends its time

Small tools for timing the pieces of one shader compile outside the emulator: SPIR-V to MSL in SPIRV-Cross, then
Metal's library and pipeline compile. What they found is in [../../TRACKER.md](../../TRACKER.md) under "MoltenVK and
shader compilation": Metal is 96.9% of about 559 ms for one real vertex and fragment pair, no compile option moves
it much, and Lichii's cache holds 2,231 pipelines for 330 fragment programs.

| File | What it does |
| --- | --- |
| `mtltime.swift` | times the Metal half of a compile the way MoltenVK drives it: `mtltime VS.metal FS.metal [safe\|relaxed\|fast]` |
| `mtlx.swift` | cold-compile timings for a vertex and fragment MSL pair with variants (optimisation, language version, math mode, parallel, second pipeline) |
| `mtlconc.swift` | whether Metal compiles several shaders at once: K renamed copies of a pair compiled concurrently |
| `variants.py` | writes the MSL variants the checks use |
| `variants_in_cache.py` | how many graphics pipelines Lichii's cache holds per fragment program, and what differs between pipelines that share one |
| `main_timed.cpp` | a timed copy of the shader-sweep driver (GPL-3.0-or-later, from Lichii) |

The inputs are shaders dumped from the game (`MVK_CONFIG_SHADER_DUMP_DIR`), which are not in this repository. Build
the Swift tools with `swiftc -O NAME.swift -o NAME`.
