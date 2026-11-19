# Patches prepared for upstream

Changes from the pinned build, cut to apply to the upstream projects' own branches. None has been sent as a pull
request from here.

| File | What it is | Applies to |
| --- | --- | --- |
| `dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch` | One A64 code cache shared by a process's cores on arm64, with tests | Lichii PR #2101's head `72ff982a3c` |
| `02-moltenvk-mesh-cull-mode-pr2842-b93bdef3.patch` | The pipeline's cull mode applied to mesh draws | MoltenVK PR #2842's head `b93bdef3` |
| `moltenvk-mesh-cull-mode.patch` | The same fix as first made, a plain diff | the pinned MoltenVK tree |
| `maxPushDescriptors-16.patch` | `maxPushDescriptors` reported as 16 | MoltenVK `main` `5189f8de` |
| `04a-lichii-hmma-through-workgroup-memory-nx2-d2ca3297.patch` | Shuffle-free multiply for the game's upscaling network. Assumes 32-lane subgroups; needs a guard for other sizes | Lichii `nx2` `d2ca32974d` |
| `04b-lichii-uint8-indices-widened-on-cpu-nx2-d2ca3297.patch` | 8-bit indices widened on the CPU | Lichii `nx2` `d2ca32974d` |
| `04c-lichii-list-indirect-moltenvk-limit-nx2-d2ca3297.patch` | List-indirect draws enabled on MoltenVK | Lichii `nx2` `d2ca32974d` |
| `05-moltenvk-keep-encoder-across-barriers-main-5189f8de.patch` | The Metal render encoder kept open across barriers, without the profiler and App Nap hooks | MoltenVK `main` `5189f8de` |

The three `04` patches are parts of `patches/lichii/0006-…` with the `P60_*` switches removed; `05` is
`patches/moltenvk/0007-…` and `0008-…` together.
