# Research

Finished write-ups, one folder per topic. Each explains a result in order and marks every claim as measured or read
from the code. What each one led to in the pinned build is a row in [../TRACKER.md](../TRACKER.md).

| Topic | Start here | Also |
| --- | --- | --- |
| Performance on the Mac: where the frame time went and what was fixed | **start here:** [mac-performance/README.md](mac-performance/README.md) | [shots/](mac-performance/shots/) |
| The measured path from 29 ms to 19 ms | [path-to-60fps/README.md](path-to-60fps/README.md): overhead fixes, upscaler options, the remaining GPU idle | |
| Why the first combined build ran at 29–31 ms | [allinone-frame-breakdown/README.md](allinone-frame-breakdown/README.md): GPU-bound; the game's upscaling network costs 7.9 ms because its tensor multiplies are emulated with shuffles | |
| Lichii's settings and switches, measured one by one | [emulator-options/README.md](emulator-options/README.md): the defaults win almost everywhere; keeping the Metal encoder open is 2–2.5 ms faster; the walk hitch is a JIT cache flush | harness in [../tools/harness/](../tools/harness/README.md) |
| One JIT code cache shared by the guest cores, on arm64 | [shared-jit-cache/README.md](shared-jit-cache/README.md) | tools in [../tools/jit-cache/](../tools/jit-cache/README.md) |
| White specks on the Kokiri cave wall | [mesh-white-specks/README.md](mesh-white-specks/README.md): mesh draws ran with a left-over cull mode | [../tools/statecheck/](../tools/statecheck/README.md), [../tools/speckcheck/](../tools/speckcheck/README.md) |
| Five compute shaders failing on MoltenVK main | [compute-buffer-bounds/README.md](compute-buffer-bounds/README.md): 37-buffer push descriptor sets overflow Metal's 31 slots | [repro/](compute-buffer-bounds/repro/): standalone Vulkan reproduction |
| Native mesh shaders on Metal | [mesh-native-colours/README.md](mesh-native-colours/README.md): why native foliage was wrong | [mesh-threadgroup-memory/](mesh-threadgroup-memory/README.md), [mesh-fallback/](mesh-fallback/README.md), [metal-validation/](metal-validation/README.md) |
| The game's shaders, extracted | [shader-extraction/README.md](shader-extraction/README.md) | |
| The patch series on current Lichii (the pin's move of 2026-11-19) | [port-to-current-lichii/README.md](port-to-current-lichii/README.md) | |
| Alternatives to MoltenVK and to Lichii | [moltenvk-offramp/README.md](moltenvk-offramp/README.md) | [nxnative/](nxnative/README.md) |

`logs/` holds two emulator logs the write-ups quote.

Paths that start with `extractor/`, `emulator/pad/`, `emulator/debug/`, `emulator/memwatch/`, `dump/` or `dump-out/`
belong to the glitch-research repository this one grew out of; they are not here. Run folders named `ab-<date>-<time>`
are local run data under `tools/harness/runs/` and are not tracked.
