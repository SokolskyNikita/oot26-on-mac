# statecheck: does Metal hold the raster state Vulkan asked for?

A check for one class of MoltenVK fault: a draw that runs with the wrong cull mode, winding, fill mode, depth clip
mode, depth bias, viewport, scissor or stencil reference, because MoltenVK set the wrong value on the Metal encoder
or did not set it at all. It replays a recorded GPU trace, records both sides of every draw, and reports each draw
where they disagree. Built 2026-11-17 after the white specks in Kokiri Forest, which were this kind of fault (mesh
draws ran with the cull mode a previous draw had left behind; the fix is
`patches/moltenvk/0010-mesh-apply-the-pipeline-s-cull-mode-to-mesh-draws.patch`).

It does not look at shaders, at Lichii's translation from the guest GPU to Vulkan, or at timing. The limits are
listed at the end.

## How it works

```
Lichii (eden-cli --replay) ──Vulkan──▶ vkspy ──Vulkan──▶ MoltenVK ──Metal──▶ mtlspy ──▶ Metal
                                         │                                     │
                                  LABEL.vk.log                          LABEL.state.log
                                         └────────── statecheck.py ────────────┘
```

| Part | What it does |
| --- | --- |
| `vkspy/vkspy.c` | A Vulkan library that sits in front of MoltenVK and forwards every call unchanged. It logs each graphics pipeline's raw create info and, at every draw, the raw dynamic state of that command buffer. |
| `mtlspy/mtlspy.m` | A library inserted into the process that hooks the Metal encoder. With `MTLSPY_STATE_OUT` it logs, at every Metal draw, the raster state that encoder holds and which values were ever set on it. |
| `statecheck.py` | Joins the two logs by draw and applies the rules. |
| `record.sh` | Replays a trace through both recorders. |
| `selftest.py` | Puts deliberate bugs into MoltenVK and checks that each is reported. |
| `build.sh` | Builds the two libraries. |

Three points of the design matter:

- **Neither side comes from MoltenVK.** The request is taken where the program hands it to Vulkan and the result
  where MoltenVK hands it to Metal. The expected Metal value is worked out in `statecheck.py` from the request alone.
  The specks fault was a wrong idea inside MoltenVK about the pipeline (a mesh pipeline was treated as a point list),
  so a check that read MoltenVK's own view of the pipeline would have agreed with the fault.
- **The two logs name the same draw.** vkspy inserts a debug label `vkspy:d<id>` before each draw and `vkspy:x`
  after it. MoltenVK turns a label into `insertDebugSignpost:` on the Metal encoder, where mtlspy reads the id. A
  Metal draw with no id is one MoltenVK made on its own (a clear or a resolve) and is not checked.
- **"Never set" is recorded.** A Metal encoder starts with Metal's defaults. mtlspy logs which values were set on
  each encoder, so a report says whether the wrong value was Metal's default (never applied) or was applied by an
  earlier draw (left over).

## Running it

Build once, then record and check:

```bash
./build.sh
```

```bash
./record.sh LABEL /path/to/libMoltenVK.dylib
```

```bash
python3 statecheck.py runs/LABEL
```

`record.sh` needs a Lichii `eden-cli` that has `--replay` and a `.lxtrace` file. Its defaults point at a local build
tree and at the Kokiri cave wall trace of 2026-11-17 (local, not tracked); `EDEN_CLI=path` and `TRACE=path` choose
others, and `FRAMES=n` sets how many presents to replay (default 20). A trace is recorded with the debug server's
`trace_record` command, which `../harness/ab.py` can call after a walk (Lichii's `docs/nx2/gpu-trace.md` describes
the format). The replay needs no game and no emulator lock, and one run takes about
20 seconds.

`statecheck.py` exits 1 if any draw differs or the logs do not join one to one. `statecheck.py --rules` prints the
rules and the allowed differences. Everything a run writes goes to `runs/`, which git ignores.

Never start `eden-cli` outside `record.sh`, not even with `--help`: away from `runs/` it uses the real emulator's
data folder and rotates its log.

## Reading the output

```
join: 12234 Vulkan draws, 12234 tagged Metal draws, 564 Metal draws with no tag (MoltenVK's own)

rule          agree  allowed  differ     n/a
cull          11955        0     263      16
...
reports: 263 rule failures in 16 groups (rule, pipeline, requested, Metal)
      30 draws  cull  pipeline #235 (0x7a352cdc00, stages 0xd0) mesh: requested 2, Metal has 0  [never set on that encoder: Metal's default]  first draw id 967
```

Each draw gets one verdict per rule:

| Verdict | Meaning |
| --- | --- |
| agree | Metal holds what the request needs. |
| allowed | Metal differs in a way MoltenVK intends. The reason is named. |
| differ | Metal holds something else. These are the reports. |
| n/a | The state cannot affect this draw (cull on a point list, stencil reference with the stencil test off), or the script cannot work out what to expect. The reason is named. |

Reports are grouped by rule, pipeline, requested value and Metal value. `pipeline #N` is the N-th pipeline created
in the run; its `P` line in `LABEL.vk.log` has the full create info. `first draw id` finds the draw in both logs
(`id=` in the `D` line, `tag=` in the `M` line). Numbers are Vulkan's and Metal's own enum values.

## The rules

| Rule | Applies to | Metal must hold |
| --- | --- | --- |
| topology | Draws that are not mesh draws and have no tessellation or geometry stage | The primitive type of the Vulkan topology |
| cull | Triangles | None, front or back, as requested |
| winding | Triangles | Counter-clockwise for Vulkan counter-clockwise, clockwise for clockwise |
| fill | Triangles | Fill or lines, as the polygon mode says |
| depthClip | Every draw | Clip mode when Vulkan's depth clip is on, clamp mode when it is off |
| depthBias | Triangles | The requested constant, slope and clamp when bias is enabled, zeros when it is not |
| viewport | Every draw | The first viewport's origin, size (a negative height included) and depth range |
| scissor | Every draw | The first scissor, cut down to the framebuffer |
| stencilRef | Draws with the stencil test on | The low 8 bits of the front and back reference |

A requested value comes from the command buffer when the pipeline declares that state dynamic and from the pipeline
otherwise. A dynamic value that no `vkCmdSet` call set is reported as an undefined request.

Six differences are intended by MoltenVK and accepted, each under its own name: "cull both faces" and dynamic
rasterizer discard done with an empty scissor, depth clip and clamp both on or both off (MoltenVK finishes these in
the shader), a reversed viewport depth range passed swapped, and a triangle fan drawn as a triangle list.

## What it found and how it was checked

All on the Kokiri cave wall trace, 20 presents, 12,234 draws (measured 2026-11-17, repeated from this folder on
2026-11-18):

| MoltenVK | Result |
| --- | --- |
| Without the cull fix (the library of the MoltenVK #2901 test build, before the fix) | 263 cull failures in 16 groups, all mesh pipelines. 223 draws asked for back-face culling and ran with none, never set on that encoder; 40 asked for none and ran with back-face culling left by an earlier draw. Every other rule agrees. |
| With the cull fix | No reports. |

`selftest.py` checks that the rules catch real faults. It applies one deliberate bug at a time to MoltenVK's
`MVKCommandEncoderState.mm`, builds the library, records and checks:

| Fault | Rule that must report it | Result | Draws reported |
| --- | --- | --- | --- |
| Winding set inverted | winding | detected | 12,803 |
| Cull mode not applied again on a new encoder | cull | detected | 3,696 |
| Depth bias not cleared when a draw disables it | depthBias | detected | 20 |
| Depth clamp request ignored | depthClip | detected | 309 |
| Negative-height viewport made positive | viewport | detected | 12,818 |
| Changed scissor not applied | scissor | detected | 241 |
| Changed viewport not applied | viewport | no effect | 0 |

"No effect" means the fault left every recorded Metal value the same as the unfaulted library's on this trace, so
there was nothing to detect; it is not counted as a miss. The winding and viewport faults also change how many draws
the replay issues (12,919), and the logs still join one to one.

```bash
python3 selftest.py --src /path/to/MoltenVK
```

The tree must already be configured and built with CMake (`--build DIR`, default `build-par`). The source file is
put back after each fault and the library found beforehand is put back byte for byte at the end, because rebuilding
the untouched source does not give an identical library. Do not run it while anything else builds in that tree.
It takes a few minutes; `--reuse` keeps fault libraries already in `runs/faults/`.

## Limits

- **One trace.** Everything above is one spot in one game. A rule only proves something for the draws a trace
  contains.
- **Not exercised by that trace:** the stencil reference rule (the stencil test is never on), all six allowed
  differences, and cull, winding and topology as dynamic state (Lichii on MoltenVK sets them in the pipeline). That
  code is written and has never run on real data.
- **Depth bias on lines and points is not checked.** Vulkan biases only polygons. Whether Metal applies a left-over
  bias to lines is not known, so a leak there would go unreported.
- **Not recorded:** blend, colour write mask, sample count, the contents of the depth-stencil state, vertex,
  fragment and compute bindings, textures, and any viewport or scissor after the first.
- **The labels may not be free.** Replays differ from run to run by up to 0.2 % of pixels with or without the
  labels, so it is not shown that inserting them changes nothing (`VKSPY_NOLABEL=1` records without them).
- **A pipeline handle is reused** after the pipeline is destroyed. `statecheck.py` reads the log in order and takes
  the last pipeline created under a handle before each draw; anything else that reads `LABEL.vk.log` must do the
  same.
- **Out of scope:** wrong shader output with correct state (that needs the shader run on both sides and its outputs
  compared), Lichii's guest-to-Vulkan translation, and faults that depend on timing, which a replay does not reproduce.

## Next step if it is taken further

Record traces at the other save locations and run them. Add blend, depth-stencil contents and bindings only if that
finds something or a new fault calls for them.
