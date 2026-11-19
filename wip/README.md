# Unfinished threads

Work that stopped before its question was answered. Each folder's README says where it stands and what the next step
is; the same threads are rows under "Open" in [../TRACKER.md](../TRACKER.md). A thread that finishes moves to
`research/`.

| Folder | Question | State |
| --- | --- | --- |
| [shader-prebuild/](shader-prebuild/README.md) | Can the game's shaders be built before play, so a first visit does not stutter? | Works in a test build: compile work in a first visit 175.6 s → 7.3 s with a small predicted file. Not in the pinned build: the full file overflows Metal's 1 GiB shader cache. |
| [shader-metal-analysis/](shader-metal-analysis/README.md) | Do the Metal translations of the game's shaders compute what the originals do? | Done offline: the translation is bit-exact. A third of automatic-mip samples are conditional per pixel and get the wrong mip on Apple GPUs; the fix is prototyped and has not been seen in the game. |

`<thread>/local/` holds build trees and run data. It is not tracked.
