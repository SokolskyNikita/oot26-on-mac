# Unfinished threads

Work that stopped before its question was answered. Each folder's README says where it stands and what the next step
is; the same threads are rows under "Open" in [../TRACKER.md](../TRACKER.md). A thread that finishes moves to
`research/`.

| Folder | Question | State |
| --- | --- | --- |
| [shader-prebuild/](shader-prebuild/README.md) | Can the game's shaders be built before play, so a first visit does not stutter? | Works in a test build: compile work in a first visit 175.6 s → 7.3 s with a small predicted file. Not in the pinned build: the full file overflows Metal's 1 GiB shader cache. |
| [shader-metal-analysis/](shader-metal-analysis/README.md) | Do the Metal translations of the game's shaders compute what the originals do? | Done offline: the translation is bit-exact. A third of automatic-mip samples are conditional per pixel and get the wrong mip on Apple GPUs; the fix is prototyped and has not been seen in the game. |
| [hypervisor/](hypervisor/README.md) | Can Lichii's Hypervisor CPU backend, which runs guest code natively, replace the JIT? | The render race is found and fixed and the backend walks faster than the JIT (17.5 ms against 22 ms) and loads twice as fast, but 2 of 26 boots had a corrupted picture. The untested read-path fix and the remaining tests are listed in its README. Not built or run since it was recovered. |

`<thread>/local/` holds build trees and run data. It is not tracked.
