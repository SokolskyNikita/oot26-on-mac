# Moving off MoltenVK: where Mac Vulkan is heading, and what it means for this project's mesh shader work

Survey made on 2026-11-16, by reading only (nothing was built or run). Every claim links to its source and gives the
source's date. **Stated** means a maintainer or the project said it; **inferred** means it is a reading made for this survey.

Why it matters: the remake draws with mesh shaders. Under MoltenVK, Lichii either emulates them or uses
MoltenVK main + KhronosGroup/MoltenVK#2842/#2843 for native ones (4 of the 53 mesh shaders reached in Kokiri Forest,
and 10 of the game's 440, exceed Metal's 32 KB threadgroup memory; see
[mesh-threadgroup-memory](../mesh-threadgroup-memory/README.md)), plus a local `maxPushDescriptors` fix. The pinned
build takes the second route with local fixes; see [mac-performance](../mac-performance/README.md).

## Summary

- **MoltenVK is deprecated, and nothing has been merged since that day.** Khronos added the notice on 2026-10-13. The
  last merge was the notice itself. More than 30 community PRs are open, #2842 and #2843 among them, and none has had
  a reply.
- **KosmicKrisp is the stated successor on Apple Silicon.** It is conformant with Vulkan 1.4, needs macOS 26 or
  later, and is shipped in the Vulkan SDK, in Mesa and in Homebrew's `mesa`. It **does not offer
  `VK_EXT_mesh_shader`**. The lead developer's wish list on Mesa ([#14251](https://gitlab.freedesktop.org/mesa/mesa/-/issues/14251))
  lists "Mesh shaders" among things "of no priority now". Metal mesh shaders are planned only *inside* the driver.
  Geometry shader support was merged to Mesa main on 2026-10-29; it is not in the 26.3.0 release.
- **Lichii has no KosmicKrisp or native Metal work.** One user asked for KosmicKrisp. Its Vulkan code was inherited
  from Eden, which already runs on drivers it rates as unsuitable "to allow KosmicKrisp". Eden's docs say its plans
  have shifted toward KosmicKrisp.
- **Other emulators:** Dolphin, PCSX2, DuckStation, Cemu and Ryubing have native Metal backends. RPCS3 now ships
  KosmicKrisp next to MoltenVK and plans to drop MoltenVK around late 2027.
- **What changes the picture: nxnative** (`seedds/nxnative`). It runs Switch 2 games, OoT included, natively on Apple
  Silicon with NVN translated straight to Metal. It reports ~60 fps in Kokiri Forest, with mesh shaders as Metal
  object/mesh functions.

---

## 1. MoltenVK

**The deprecation.** The README notice was added by Khronos's bot account in
[KhronosGroup/MoltenVK#2874](https://github.com/KhronosGroup/MoltenVK/pull/2874), merged 2026-10-13 17:32 UTC (commit
`cf2dafb`). Its wording (stated):

> Khronos has deprecated MoltenVK, its Vulkan-on-Metal implementation. This repository is now maintained by the
> community on a best-effort basis. For Vulkan on Metal, Khronos now recommends KosmicKrisp on Apple Silicon Macs.
> MoltenVK remains the recommended option for Intel-based Macs and for iOS.

Wikipedia gives the same date ([MoltenVK](https://en.wikipedia.org/wiki/MoltenVK), read 2026-11-16).
[vulkan.org/porting](https://vulkan.org/porting) carries the same notice. The same push added a `CONTRIBUTING.md`
([#2832](https://github.com/KhronosGroup/MoltenVK/pull/2832), 2026-10-13) that requires a Khronos CLA and a statement
about AI-assisted contributions.

**What "deprecated" means in practice.** Statements in the #2874 thread:

- Richard Wright (LunarG), 2026-10-21: deprecated means "no longer maintained and won't be moving forward". It may
  stay useful for a long time, like OpenGL on Apple. "MoltenVK is no longer funded, neither by Khronos or any third
  party on a full time basis." He asks developers to evaluate KosmicKrisp and to file KosmicKrisp performance gaps on
  Mesa with GFXReconstruct traces.
- squidbus (the most active MoltenVK merger, who also contributes to KosmicKrisp), 2026-10-21: this formalizes the
  status quo. MoltenVK "has not been funded for proper maintenance for a long while" and runs on volunteers.
- Richard Wright, 2026-10-23, asked whether there will be another SDK release: "if Bill does an official release",
  LunarG waits about a month and then includes it in the SDK. So a 1.4.3 is not ruled out, but nobody has committed
  to one.
- Karen Ghavam (LunarG), 2026-10-19: only three items remain for KosmicKrisp to match MoltenVK's features:
  `VK_EXT_fragment_shader_interlock`, `VK_KHR_fragment_shader_barycentric` and `VK_KHR_incremental_present`. She
  links a Mesa work item for this.

**Merge activity** (from `gh`, read 2026-11-16):

- Last release: [v1.4.2](https://github.com/KhronosGroup/MoltenVK/releases/tag/v1.4.2), 2026-07-24.
- Last merges: #2861 by squidbus on 2026-10-08, then the two Khronos housekeeping PRs on 2026-10-13. No merge since.
  Nobody has pushed to `main` since 2026-10-13 17:33.
- Between 2026-09-05 and 2026-10-08, squidbus merged about 15 community PRs. That is the volunteer pace that stopped
  at the deprecation.
- About 30 PRs opened 2026-09-24 to 2026-11-13 are still open. The newest is #2903 (2026-11-13).

**#2842 and #2843.** Both by `dttdrv`, opened 2026-09-25. Neither has a comment, review or label (read 2026-11-16):
[#2842 Add VK_EXT_mesh_shader support](https://github.com/KhronosGroup/MoltenVK/pull/2842) and
[#2843 Use specialization constant values for array sizes](https://github.com/KhronosGroup/MoltenVK/pull/2843). The
same author's #2837 (2026-09-24) is also unreviewed. Nobody has said what will happen to open PRs. *Inferred:* they
stay open until a volunteer with merge rights picks them up, and since 2026-10-08 nobody has.

**Performance against KosmicKrisp, as users report it** (#2874 thread): SRSaunders, on an M1 with SDK 1.4.363.0,
2026-10-21: RBDoom3BFG ran at 102 fps under MoltenVK and 51 fps under KosmicKrisp at 720p. Across Sascha Willems'
samples KosmicKrisp averaged 84% of MoltenVK's frame rate (2026-10-22), and timeline semaphores are the suspected
cause.

## 2. KosmicKrisp

**Who and where.** LunarG writes and maintains it; Aitor Camacho Larrondo has led it since November 2024. Google
sponsored the original work for the Android Emulator on Mac. The code is in Mesa (`src/kosmickrisp`), with docs at
[docs.mesa3d.org/drivers/kosmickrisp.html](https://docs.mesa3d.org/drivers/kosmickrisp.html). It is MIT-licensed. CI
runs at LunarG on M1, M2 and M4, not in Mesa's CI. Sources: [LunarG product page](https://www.lunarg.com/products/kosmickrisp)
(2026-11-02) and the XDC 2026 talk ["KosmicKrisp: Production Ready!"](https://indico.freedesktop.org/event/12/contributions/538/attachments/377/541/KosmicKrisp_Production_Ready.pdf)
(Camacho Larrondo, about 2026-09-30).

**Version and status.**

- Vulkan 1.4 conformant. See the [LunarG announcement](https://www.lunarg.com/kosmickrisp-achieves-vulkan-1-4-conformance-on-apple-silicon/)
  (the body dates it September 2026, though its header reads "September 25, 2025"), the
  [Khronos news item](https://www.khronos.org/news/archives/kosmickrisp-achieves-vulkan-1.4-conformance-on-apple-silicon)
  (2026-10-01) and [Phoronix](https://www.phoronix.com/news/KosmicKrisp-Vulkan-1.4-2026) (2026-10-03).
- Mesa first exposed 1.4 in 26.2 ([announcement](https://lists.freedesktop.org/archives/mesa-dev/2026-August/226690.html),
  2026-08-05).
- The XDC deck lists new support for tessellation, robustness2 and multi-draw. It says KosmicKrisp runs on all M1–M5
  chips and the A18 Pro.

**Extensions that matter here.** From Mesa's [features.txt](https://docs.mesa3d.org/features.txt) (read 2026-11-16;
`kk` is KosmicKrisp):

| Item | KosmicKrisp |
| --- | --- |
| `VK_EXT_mesh_shader` | **No.** Listed for anv, lvp, nvk, radv and vn only. Not hk (Asahi's HoneyKrisp) either |
| `VK_KHR_push_descriptor` | Yes |
| `geometryShader` | Merged to Mesa main on 2026-10-29 ([!44786](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/44786) "kk: Add geometry shader support"). Its merge commit is on `main` only, so it is not in Mesa 26.3.0 or Homebrew's `mesa` (*inferred*: expected in 26.4). The XDC deck still listed it under "What's next" |
| `VK_EXT_transform_feedback` | Open MR [!44928](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/44928) (2026-10-05) |
| The three MoltenVK-parity gaps above | Not done. Tracked in [#14209](https://gitlab.freedesktop.org/mesa/mesa/-/issues/14209) (opened 2026-10-12). `VK_KHR_fragment_shader_barycentric` is a draft MR ([!45585](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/45585), 2026-10-25) |

**Mesh shaders, all the evidence found** (stated):

- XDC 2026 "Tips & tricks": unrolling, tessellation and indirect draw count currently break render passes. The
  "Plan to move them to mesh shaders and vertex dispatch to avoid break".
- XDC 2026 "What's next": "Move certain features to mesh shaders" (under performance). Under extensions it lists
  geometry shaders, descriptor heaps and shader objects. `VK_EXT_mesh_shader` is not listed.

- Mesa [#14251 "kk: wish list"](https://gitlab.freedesktop.org/mesa/mesa/-/issues/14251), opened by the lead
  developer (`aitor`) on 2025-11-06 and last updated 2026-11-11. It tracks "things KK will aim to implement but are of
  no priority now". "Mesh shaders" is unticked, next to ray tracing, shader objects and descriptor heaps. "Tessellation
  and geometry shaders" is ticked. No comment in the thread asks for mesh shaders.
- Mesa [#16316](https://gitlab.freedesktop.org/mesa/mesa/-/issues/16316) and
  [#16317](https://gitlab.freedesktop.org/mesa/mesa/-/issues/16317) (aitor, 2026-09-14): move unrolling and
  tessellation, both now done with compute, onto Metal mesh shaders. The goal is to stop splitting the render encoder.
  This is internal use, not the Vulkan extension.

*Inferred:* `VK_EXT_mesh_shader` is acknowledged but unscheduled. Nothing suggests it is coming in the next few
releases. When it does come, it would map onto Metal's mesh stages and inherit the same 32 KB limit.

Where this was searched (2026-11-16, Mesa GitLab API, with a token): issues and MRs labelled KosmicKrisp matching
"mesh" or "geometry", and all issues matching "VK_EXT_mesh_shader". No KosmicKrisp issue or MR for the extension was
found.

**Binding limits.** These are Metal's limits, not MoltenVK's. Apple's
[Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf) (2026-10-23 edition) give,
for every Apple GPU family:

- 31 buffer and 16 sampler entries per stage argument table;
- **32 KB** of threadgroup memory;
- a 16,384-byte mesh payload.

KosmicKrisp runs on Metal 4 with argument buffers, so binding counts are probably not capped the same way (inferred).
Its per-stage descriptor limits were not found in a primary source; `vulkaninfo` on the driver would settle it. The
32 KB threadgroup limit is a hardware/Metal limit that no driver can lift. So any driver that maps Vulkan mesh
shaders onto Metal mesh shaders would hit the game's oversized shaders too (inferred).

**Distribution and requirements** (stated):

- Apple Silicon only, macOS 26 or later (Metal 4).
- Ships in the [Vulkan SDK](https://vulkan.lunarg.com/doc/view/latest/mac/getting_started.html) (1.4.363.0 is
  current; it installs next to MoltenVK and is picked with `VK_DRIVER_FILES`), in Mesa releases, and in Homebrew's
  `mesa`. The [formula](https://github.com/Homebrew/homebrew-core/blob/main/Formula/m/mesa.rb) (last changed
  2026-11-10, now at 26.3.0) builds `kosmickrisp` on Tahoe and later.
- It must be loaded through the Vulkan loader. It does not need or support `VK_KHR_portability_enumeration`.
- LunarG says apps may bundle the loader and KosmicKrisp in the app, and may choose between it and MoltenVK at run
  time.
- The SDK guide says KosmicKrisp will become the SDK's default, and MoltenVK a legacy optional component until it is
  retired from the SDK.
- iOS: not supported. LunarG's tests show better CTS results than MoltenVK, but it has no resources to support iOS.

**Performance against MoltenVK.** LunarG's numbers (XDC 2026, M3 Pro, macOS 27): GFXBench Aztec high and normal at
107% and 103% of MoltenVK; 3DMark Wild Life and Wild Life Extreme at 99% and 96%. Their own caveat: these tests use
"Vulkan 1.1 usage". The users' numbers in section 1 run from 50% to 84%. No benchmark of an emulator or of mesh-heavy
work was found.

## 3. Lichii and its lineage

Lichii (`zortos293/Lichii`, created 2026-10-31) says it "builds on Eglantine, Eden, yuzu and Sudachi"
([README](https://github.com/zortos293/Lichii)). Eglantine's community repo is `Eglantine-Community/Eglantine`
(created 2026-10-29).

**Lichii** (searched for kosmickrisp, metal and moltenvk in issues and PRs, 2026-11-16):

- KosmicKrisp: one user request in [#13](https://github.com/zortos293/Lichii/issues/13) (2026-11-01, M5 Pro; "Potential
  graphics support for KosmicKrisp would be appreciated"). [#16](https://github.com/zortos293/Lichii/pull/16), which
  closed it, says KosmicKrisp compatibility "still need[s] testing on real hardware". No other mention found.
- A native Metal backend or dropping MoltenVK: **not found**. All the Mac work is MoltenVK workarounds. Examples:
  [#1862](https://github.com/zortos293/Lichii/pull/1862) (16-sampler limit, merged 2026-11-15),
  [#1375](https://github.com/zortos293/Lichii/pull/1375) and [#841](https://github.com/zortos293/Lichii/pull/841)
  (cached task/mesh pipelines without `VK_EXT_mesh_shader`). Open:
  [#630](https://github.com/zortos293/Lichii/pull/630) and [#631](https://github.com/zortos293/Lichii/pull/631).
- [#1970 "Better MacOS Support with Hypervisor"](https://github.com/zortos293/Lichii/pull/1970), by HyperCed, opened
  2026-11-16. Still open, with only an automated CodeRabbit review. It adds a Hypervisor.framework CPU backend. It
  also checks mesh-shader device limits and emulates when they are exceeded (its effect on this game is in [mesh-fallback](../mesh-fallback/README.md)).
- [#1944 "Direct NVN renderer"](https://github.com/zortos293/Lichii/pull/1944), a draft by dzervas, opened 2026-11-16.
  It hooks the game's NVN calls and replays them into Vulkan, using code from Banana Native, an Android port of
  nxnative. It states that nxnative's "Apple/Metal files are not imported". *Inferred:* if it lands, the GPU path gets
  shorter, but on a Mac it still goes through a Vulkan driver.
- Lichii keeps Eden's macOS loader. `vulkan_library.cpp` honours `LIBVULKAN_PATH`, then the bundled `libvulkan.1.dylib`,
  then `libMoltenVK.dylib`. It names `VK_DRIVER_ID_MESA_KOSMICKRISP`. On an unsuitable driver it logs "Unsuitable
  driver - continuing anyways".

**Eglantine:** no KosmicKrisp or Metal-backend issue or PR found. Its Mac work is MoltenVK clamps, e.g.
[#33](https://github.com/Eglantine-Community/Eglantine/pull/33) (2026-10-30).

**Eden** (Switch 1, [git.eden-emu.dev](https://git.eden-emu.dev/eden-emu/eden)):

- [v0.0.4 release notes](https://git.eden-emu.dev/eden-emu/eden/releases/tag/v0.0.4) (2025-12-21): drivers rated
  unsuitable now continue, which "also allows the experimental KosmicKrisp MESA driver to run on macOS".
- Its QuickStart ([mirror](https://github.com/eden-emulator/mirror/blob/master/docs/user/QuickStart.md), last changed
  2026-11-13) says Mac support is "very reliant on MoltenVK developments". It says plans "have shifted to properly
  provide support for KosmicKrisp and similar new GPU endeavors, but macOS users still are bound to MoltenVK". It
  points users to Asahi Linux.
- Eden's issue tracker on Forgejo was not searched; only the releases and the docs were read.

**Who is doing the work:** nobody is visibly working on KosmicKrisp or Metal in this line. In Lichii, the Mac-specific
work is HyperCed's #1970 and the MoltenVK workaround PRs.

## 4. Other emulators on macOS

| Emulator | Choice | Evidence (date) |
| --- | --- | --- |
| **Ryujinx / Ryubing** | Native Metal backend (experimental), Vulkan via MoltenVK as well | Ryubing [1.2.80](https://newreleases.io/project/github/Ryubing/Ryujinx/release/1.2.80) (release date not checked) merged Isaac Marovitz's Metal backend; "Auto" picks per game. Latest stable [1.3.3](https://git.ryujinx.app/projects/Ryubing/releases) (2025-10-11) still has MoltenVK fixes. KosmicKrisp: not found (Forgejo tracker not searched) |
| **Astris** (Ryujinx-based, Mac only) | Ryujinx's backends | Binaries at [V380-Ori/Astris.Binaries](https://github.com/V380-Ori/Astris.Binaries); backend details not checked |
| **MeloNX** (iOS) | MoltenVK | Its [project page](https://git.ryujinx.app/projects/MeloNX) says it emulates the GPU "using Metal (via MoltenVK)" |
| **Eden** | MoltenVK; wants KosmicKrisp | section 3 |
| **Dolphin** | Native Metal backend since 2022; Vulkan via MoltenVK too | Metal backend in `Source/Core/VideoBackends/Metal` (last touched 2025-04-12). [#14545](https://github.com/dolphin-emu/dolphin/pull/14545) (OatmealDome, opened 2026-04-03, open, updated 2026-10-15) moves to the SDK's loader and MoltenVK and adds KosmicKrisp, probably off by default. phire, 2026-07-30: "should we even be bundling MoltenVK anymore?" and suggests Metal as the default |
| **PCSX2** | Native Metal renderer | `pcsx2/GS/Renderers/Metal` (last commit 2026-09-24). No KosmicKrisp mention found |
| **DuckStation** | Native Metal device | `src/util/metal_device.mm` (last commit 2026-11-12). No KosmicKrisp mention found |
| **Cemu** | Native Metal backend, added 2025-12-06 | [Add Metal backend (#1287)](https://github.com/cemu-project/Cemu/tree/main/src/Cafe/HW/Latte/Renderer/Metal), last commit 2026-10-14. No KosmicKrisp mention found |
| **RPCS3** | Ships **KosmicKrisp and MoltenVK** | [#17735](https://github.com/RPCS3/rpcs3/pull/17735) (merged 2025-12-06) loads Vulkan ICDs; [#17902](https://github.com/RPCS3/rpcs3/pull/17902) (merged 2026-10-23) ships KosmicKrisp builds. Its author calls the next year an "evaluation period" and expects to remove MoltenVK when Sequoia support ends, around late 2027 (stated). A user in [#19986](https://github.com/RPCS3/rpcs3/issues/19986) (2026-10-29) reports KosmicKrisp fixed a MoltenVK lighting bug |
| **nxnative** (not an emulator) | Native: NVN → Metal | See section 5 |

*Inferred:* emulators whose authors had capacity wrote native Metal backends years ago. Vulkan-only emulators
(RPCS3; the yuzu line: Eden, Eglantine, Lichii) are the ones turning to KosmicKrisp. RPCS3 is the only one shipping it.

## 5. Other things that change the picture

- **nxnative** ([seedds/nxnative](https://github.com/seedds/nxnative), created 2026-10-13, very active):
  - It runs the game's own ARM code on the Mac's CPU and rebuilds NVN on Metal. It needs macOS 26.6 and Xcode 27.2.
  - Its [OoT note](https://github.com/seedds/nxnative/blob/main/dm/games/0400486024DEC000/README.md) (read 2026-11-16)
    reports that OoT v131072 plays through Kokiri Forest at about 59–60 fps on an M5 Pro (measured 2026-11-09).
  - It translates the game's task/mesh shaders into Metal `[[object]]`/`[[mesh]]` functions, with no Vulkan in between
    ([shaders.md](https://github.com/seedds/nxnative/blob/main/docs/reference/shaders.md), sections "NVN2 task and mesh
    shaders" and "Task and mesh shaders in BNSH"). It refuses a mesh shader that uses shared memory of its own.
  - A Lichii user said on Lichii#237 that they had switched to it for OoT (2026-11-05).
  - *Inferred:* for playing OoT on a Mac this already beats every Vulkan-on-Metal route. Whether it suits glitch
    research (lldb breakpoints on game code, scripted input, frame stepping) is covered in
    [nxnative](../nxnative/README.md).
- **Apple's limits are unchanged.** The 2026-10-23 Feature Set Tables still give 32 KB threadgroup memory and a 16 KB
  mesh payload for every family. Apple has not lifted the limit that the game's oversized foliage shaders exceed.
- **Mesa mesh-shader work:** NVK gained `VK_EXT_mesh_shader` in Mesa 26.2 (2026-08-05). For KosmicKrisp there is
  only the wish-list entry (#14251). Nothing was found for HoneyKrisp.

---

## Conclusions

**How long patches against MoltenVK stay useful.** They stay useful as long as this project builds its own MoltenVK.
Nobody is merging; the last merge was 2026-10-08. Lichii's bundled MoltenVK is 1.4.1 and the newest release is
1.4.2, so these fixes will not reach Lichii's bundle through upstream. *Inferred:* patches keep working for local
builds for the life of macOS 26–27 and Lichii's current Vulkan path, about a year. RPCS3's late-2027 cut-off is a
reasonable outer bound for when emulator projects stop shipping MoltenVK. They don't rot quickly, because MoltenVK
is frozen; but nothing builds on them either.

**Is an upstream PR to MoltenVK still worth sending?** As a merge, probably not:

- #2842/#2843 have had no response in 7 weeks, and nothing has merged since the deprecation.
- Khronos says nobody is funded.
- A new PR would need a Khronos CLA and the AI-contribution statement.

Two cheaper uses:

- **Comment** on #2842 with the results: the 32 KB threadgroup overflow, upstream's `maxPushDescriptors` value (287,
  which overflows Metal's 31 buffer slots; the stock app's fork sets 16, see
  [compute-buffer-bounds](../compute-buffer-bounds/README.md)) and the measured gains. That helps whoever revives it,
  and is a record if a 1.4.3 is ever cut. Done: a test report on 2026-11-16 and the cull-mode fault on 2026-11-18.
- **Send the `maxPushDescriptors` fix** as a small, separate PR. It is a one-line fix for a fault in upstream (1.4.1
  and main alike), which is the kind of PR a best-effort maintainer might still merge before a release. Low odds, low
  cost. Not sent yet.

Neither is a reason to put more effort into MoltenVK itself.

**Is a Lichii trial on KosmicKrisp worth it now?** Cheap, so yes, with low expectations:

- Mesh shaders would be emulated, as under stock 1.4.1, so the best case is about the 2026-11-16 "all emulated" figures (~34–38 ms).
  The question is whether KosmicKrisp emulates faster or slower than MoltenVK, and whether the 16-sampler and
  push-descriptor problems go away.
- Risks:
  - No `geometryShader` in 26.3.0 (it is on Mesa main). Lichii's fallback for a missing `geometryShader` is gated on
    `IsMoltenVK()` (`vulkan_device.cpp` `CHECK_FEATURE`), so on 26.3.0 it logs an error and carries on as
    "unsuitable". `brew install --HEAD mesa` would build main, with geometry shaders, but is a long build.
  - About 24 MoltenVK-specific workarounds would be switched off.
  - User reports put KosmicKrisp at 50–84% of MoltenVK.

What it would take (no Lichii rebuild):

1. Install KosmicKrisp: `brew install mesa` (26.3.0, builds it on Tahoe and later; the test Mac runs macOS 27.0.1) or the
   LunarG SDK. A loader is already installed (`vulkan-loader` 1.4.363.0).
2. Launch a copy of a Lichii app with `LIBVULKAN_PATH=<brew prefix>/lib/libvulkan.1.dylib` and
   `VK_DRIVER_FILES=<mesa prefix>/share/vulkan/icd.d/kosmickrisp_icd*.json`, so that the bundled `libMoltenVK.dylib`
   is skipped.
3. Check `vulkaninfo` first for the per-stage limits and missing features. Then run the harness as usual, when nothing
   else holds the emulator lock.

**What to watch:**

- MoltenVK:
  - [#2842](https://github.com/KhronosGroup/MoltenVK/pull/2842) and [#2843](https://github.com/KhronosGroup/MoltenVK/pull/2843):
    any review.
  - [#2874](https://github.com/KhronosGroup/MoltenVK/pull/2874): any statement about a final release.
  - The [releases page](https://github.com/KhronosGroup/MoltenVK/releases): a v1.4.3.
- KosmicKrisp:
  - Mesa [#14251](https://gitlab.freedesktop.org/mesa/mesa/-/issues/14251): the "Mesh shaders" box getting ticked,
    or an MR linked from it. Also the
    [KosmicKrisp label](https://gitlab.freedesktop.org/mesa/mesa/-/issues/?label_name%5B%5D=KosmicKrisp) and `kk` in
    `docs/features.txt` under `VK_EXT_mesh_shader`.
  - The first Mesa release containing !44786 (geometry shaders).
  - To query: `glab api "projects/mesa%2Fmesa/issues?labels=KosmicKrisp&search=mesh"` against
    gitlab.freedesktop.org.
  - LunarG's [blog](https://www.lunarg.com/learn-more/lunarg-blog/) and the SDK release notes: KosmicKrisp becoming
    the SDK default, or MoltenVK being removed.
- Lichii:
  - [#1970](https://github.com/zortos293/Lichii/pull/1970): merge, and the mesh-limit gating.
  - [#1944](https://github.com/zortos293/Lichii/pull/1944): direct NVN.
  - Any issue mentioning KosmicKrisp.
- Others:
  - Eden's QuickStart macOS section.
  - Dolphin [#14545](https://github.com/dolphin-emu/dolphin/pull/14545) and RPCS3's KosmicKrisp feedback: the first
    real-world comparisons from emulators.
- nxnative's [OoT note](https://github.com/seedds/nxnative/blob/main/dm/games/0400486024DEC000/README.md): for a fast Mac
  picture without Lichii's debugger.
- Apple's [Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf): any rise in
  threadgroup memory past 32 KB. Under every route that maps Vulkan mesh shaders onto Metal mesh shaders, that limit
  is what keeps the oversized foliage shaders out.
