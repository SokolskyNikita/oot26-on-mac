# The pinned patch series on current Lichii (`gold-next`)

**Question:** does current Lichii plus every change of the pinned series work, and how does it perform?

**State (2026-11-19):** the series is ported to the current `nx2` head, the `lichii` target compiles and links, the
patches are in [`patches/lichii-next/`](../../patches/lichii-next/), and the build boots, draws correctly and measures
the same as the pinned build in Kokiri Forest (next section). It is not the pinned build: nothing has been installed.

| | |
| --- | --- |
| Base | `zortos293/Lichii` `nx2` head `d2ca32974d439dd6d1f3ff0a2446ed9c3ab019bb`, committed 2026-11-19 10:17 UTC ("common: cap Windows zero-page unlocks at 1 MiB (#2233)") |
| Relation to build 341 | `build-341` is `9c9a1dfa56` (2026-11-17 20:06 UTC), still the latest release. The base is 106 commits after it and 202 after the pinned base `8c0558a3d3`. No tag contains the base (`git describe`: `build-316-203-gd2ca32974d`; the only tags fetched are 316 and 341). |
| Branch | `gold-next` in `build/next/lichii` (git-ignored clone), 7 commits, head `a1ee50a6ef9deade0080808e348b5012801ed707`, tree `e55524033edfdaa8b2a2fcdd0210830b0ff93e8e` |
| Patches | `patches/lichii-next/0001`–`0007`, made with `git format-patch --binary --zero-commit -N d2ca32974d..gold-next`. Applied to the base the way `build.sh` applies a series (author as committer, `--committer-date-is-author-date`) they give the same commit and tree ids (checked). |
| MoltenVK | Not touched. The port keeps the pinned library. |


## Measured against the pinned build (2026-11-19)

Run ab-20261119-051617 (pinned build) and run ab-20261119-052038 (this port), local run data, not tracked. Specs
`tools/harness/specs/lichii-next-pinned.json` and `lichii-next-new.json`. Apple M4 Pro, Kokiri Forest, 600-frame
phases, one warm-up discarded, three runs each. The port ran in a private data root (`build/next/data`, with a cloned
copy of the shader cache) under its own bundle id, with the pinned MoltenVK library.

| | Pinned build (`8c0558a3d3` + series) | Port (`d2ca32974d` + series) |
| --- | --- | --- |
| Walk, median frame | 19.0 / 19.4 / 19.4 ms | 19.1 / 18.7 / 18.6 ms |
| Walk, 95th percentile | 25.3 / 25.6 / 25.7 ms | 26.2 / 24.2 / 25.3 ms |
| Standing after the walk, median | 16.6 / 16.6 / 16.7 ms | 16.4 / 16.5 / 16.6 ms |
| Boot | 14.5 / 16.5 / 18.6 s | 16.5 / 14.5 / 16.5 s |
| Boot to in-game | 35.8 / 38.3 / 39.8 s | 38.6 / 35.9 / 39.5 s |
| Memory | 20.0 GiB | 19.0–20.0 GiB |
| Picture | clean (clipped 3.2%) | clean (clipped 3.0%; looked at) |

- **It works and it is no slower.** The differences are inside run-to-run noise; the 202 upstream commits bring no
  measurable frame-time change at this spot with these settings.
- **First boot in the private root:** 102.3 s to the title, 127.0 s to in-game. The copied pipeline file was
  accepted (same MoltenVK cache id); the time is Lichii re-stamping its records and Metal compiling into an empty
  cache of its own.
- **The installed build's folders were not touched:** sizes, times and checksums of its shader caches, config,
  master, saves and mods were identical before and after the port's five runs.
- Not tested: any other area, the Hypervisor backend, the bilinear stand-in and `P60_RUN_AHEAD` (ported as text
  only), a session longer than one walk.

## What happened to each patch

Every commit keeps its original subject, author and author date; the committer date equals the author date.

| Pinned patch | In `gold-next` | What happened |
| --- | --- | --- |
| `0001` PR #1970 (HyperCed, open) | `0001`, `ff12c242f2` | **Replaced by the PR's current head `b697762630`**, squash-merged onto the base. Two conflicts, both include lists (`texture_cache.h`, `texture_cache_base.h`), resolved by keeping both sides' includes. The commit body names the new head. |
| `0002` mesh demotion by threadgroup size (ours) | `0002`, `3f9094eb83` | Ported cleanly (cherry-pick, no conflict, same lines). |
| `0003` PR #2022 (RomainROCH) | – | **Dropped: merged upstream.** Its commit `f1f0dcc13a` is an ancestor of the base (merge `01ea8b2d51`); the three files it changed carry exactly the lines of the old squash (`CanSeedMeshVertexInput` in `mesh_vertex_input.h`, its use in `vk_pipeline_cache.cpp`, the test). |
| `0004` PR #1902 (Terobyte, open) | `0003`, `37089d9bed` | **The PR's current head, which is still `c7e22dabc9`** (the head the pinned squash was made from), squash-merged onto the base. No conflict; the same lines as the old squash. |
| `0005` NaN guard for unwritten mesh vertices (ours) | `0004`, `2552b4222d` | Ported cleanly (same lines). Upstream changed `emit_spirv_mesh.cpp` once since (`31f1378a38`, output stage buffer read-back), in other functions. |
| `0006` frame-time fixes and `P60_*` switches (ours) | `0005`, `5e490f7ca7` | Ported cleanly: all 16 files, same lines, every switch kept. See the notes on the bilinear stand-in and on `04a`–`04c` below. |
| `0007` JIT invalidation entry points (ours) | `0006`, `c3c8917161` | Ported cleanly (same lines). |
| `0008` shared A64 code cache, arm64 (ours) | `0007`, `a1ee50a6ef` | **Ported with one change**, in `arm_dynarmic_64.cpp` / `.h` (below). The 15 dynarmic files, `k_process.cpp` and the stutter-trace files are byte-identical to the pinned tree: upstream has not touched `src/dynarmic` since the pinned base. |

Checked for each ported commit by comparing the added and removed lines per file against the pinned commit: no
differences except the ones listed here.

### PR #1970: old squash against the new head

The pinned squash was made from head `1f76c9ff56` (2026-11-16). The current head `b697762630` (2026-11-17) is that
commit plus two merges of `nx2` (`ad3068b7a6`, `b697762630`); HyperCed has added no commit of his own. The PR's own
diff (head against its merge base with `nx2`) is the same at both heads, apart from context that the `nx2` merges
moved. The PR is 191 commits behind the base and GitHub reports it as conflicting.

Merged onto the base, the squash changes the same 55 files with the same added and removed lines as the pinned
`0001`, with one exception: the pinned squash removed two `.gitignore` lines (`# Python bytecode`, `__pycache__/`),
the new one keeps them.

For `0002`, `0005` and `0006`, which build on its mesh shader code: **nothing they depend on changed.**
`mesh_fallback_limits.h`, the demotion code in `vk_pipeline_cache.cpp`, `emit_spirv_mesh.cpp`, `emit_spirv_atomic.cpp`
and the `spirv_emit_context` changes are line-for-line what the pinned build has, and all three patches applied
without a conflict.

### The one change in the shared code cache patch

Upstream (between the two bases) gave each core's `DynarmicCallbacks64` its own invalidation counter
(`std::atomic<u32> code_generation`, `cached_code_generation`) so that `MemoryReadCode` re-reads its cached code page
after `ClearInstructionCache` / `InvalidateCacheRange`, and constructs `m_cb` with `std::in_place` because the atomic
makes the class immovable. The pinned patch solves the same problem with one process-wide counter
(`g_code_invalidations`), because with a shared cache a core may translate code another core invalidated.

In `gold-next` the process-wide counter is used and upstream's per-core pair is removed; upstream's
`m_cb(std::in_place, *this, process)` is kept. A per-core counter alone would be wrong for the shared cache, and
keeping both would be redundant: every bump of the per-core one is also a bump of the global one.

## Judgment calls

| Decision | Alternative |
| --- | --- |
| Base is the `nx2` head, not `build-341` | `build-341` (`9c9a1dfa56`), 106 commits older. The owner said "341" meaning current Lichii, and `patches/upstream/04a`–`04c` are cut for this head. |
| #1970 and #1902 are squash merges of the PRs' current heads | Re-applying the old squashes with `git am -3`. For both PRs the result is the same lines either way (see above). |
| `0006` is carried whole, with its switches, rather than replaced by `patches/upstream/04a`–`04c` | Using `04a`–`04c` plus a rest patch. The three split patches apply to the base, and base + `04a` + `04b` + `04c` differs from the ported `0006` in those functions only by the `P60_*` switches and comments. One functional difference is kept as the pinned build has it: `0006` lowers the list-indirect limit to 2^30 for every device, `04c` only on MoltenVK. On a Mac the two are the same. |
| Shared cache: process-wide invalidation counter replaces upstream's per-core one | Keeping both counters. |
| The dynarmic unit tests were built in a second build folder (`build/jit`) with the flags of `tools/jit-cache/README.md` | Not testing: the pinned flags have `LICHII_TESTS=OFF`. |
| The dependency source cache (`.cache/cpm`, 150 MB, 19 packages) was copied from `build/src/lichii` into the new clone | Letting CPM download it again. `cpmfile.json` changed between the bases; configure fetched what was missing. |

## Old behaviour that is not in the new branch

- Nothing of the series was left out. The only dropped patch is #2022, which the base contains.
- **Two upstream defaults changed between the bases**: `native_async_draws` default `Wait` → `Bounded`,
  `use_asynchronous_shaders` default `false` → `true` (`src/common/settings.h`; the seed that wrote the second into a
  new config was removed from `src/frontend_common/config.cpp`). The user's `qt-config.ini` sets both explicitly
  (`native_async_draws=1`, `use_asynchronous_shaders=true`, both `\default=false`), so a copy of it behaves the same
  in both builds; a fresh config would not.
- **The bilinear stand-in (`P60_OOT_BILINEAR=1`, off unless set) is ported as text only.** Upstream reworked the
  Ocarina upscale replacement around it (`02b6a8a55b` "replace OoT's scaled handheld upscale pass with FSR/DLSS",
  `a6e394a9d1`, `3480adf3d8`, `53964d56fe` in `ocarina_upscale.h` and `vk_rasterizer.cpp`). The hunks sit in the same
  places and compile; whether the stand-in still engages in handheld is not known.
- `P60_RUN_AHEAD` (off unless set) sits in `nx2_gsv.h`, which upstream changed five times (frame pacing); same
  caveat.
- `.gitignore` keeps the two Python bytecode lines the pinned squash removed.
- The built app bundles Lichii's own `libMoltenVK.dylib` (sha1 `0452365a…`), as the pinned build's raw output does;
  the pinned library replaces it at assembly (below).

Semantic interaction of the cleanly merged patches with the 202 upstream commits was checked by reading the hunks in
their new context and by the compiler, not by running. The areas where upstream moved most under the series:
`buffer_cache.h` (9 upstream commits, under #1902), `vk_rasterizer.cpp` (14, under `0006`), `gpu_split.cpp` (6,
under the frame trace), `vk_pipeline_cache.cpp` (9, under #1970 and `0002`), the texture cache (under #1970).

## Cache formats and the data directory

### Formats: unchanged

| What | Old base and new base | Where |
| --- | --- | --- |
| Shader cache v2 log | `lichii-cache.v2.bin`, `lichii-cache.v2.driver.bin`; `FormatVersion = 2` | `src/video_core/shader_cache_v2/cache.h:28,30`, `cache_format.h:27` |
| Vulkan pipeline cache version | `VulkanPipelineCacheVersion = 54`, compatible `{53, 52}`; file `vulkan_pipelines.fork-v54.bin` | `src/video_core/pipeline_cache_files.h:30,35,65` (`VersionedPipelineCachePath`); used at `renderer_vulkan/vk_pipeline_cache.cpp:106,1313` |
| Precache file | `warm-compute.bin`, `WarmCacheVersion` = the pipeline cache version, `WarmBuilderVersion = 3` | `src/video_core/shader_warm/shader_warm_builder.cpp:296`, `warm_records.h:22,27` |
| Pipeline key layout | `fixed_pipeline_state.{h,cpp}` unchanged | – |

The only change under `shader_cache_v2/` is a chunked read in `cache_file.cpp` (a MinGW fix). No file would be
rejected or deleted for its version, and the driver pipeline file's identity comes from MoltenVK, which this port
does not change.

### But the files carry two build stamps, and both differ

Lichii hashes its shader sources at build time (`src/video_core/CMakeLists.txt:559–607`,
`CMakeModules/GenerateShaderLoweringStamp.cmake`):

| Stamp | Hash of | Pinned build | `gold-next` |
| --- | --- | --- | --- |
| `LoweringStamp` | `shader_recompiler/frontend/ampere/*`, `native_lowering.{cpp,h}`, `mkw_wave_workaround.h` | `0x88561304c6618a81` | `0x553dae88b1943c5f` |
| `EmissionStamp` | the whole recompiler except the OpenGL backends, `shader_environment.{cpp,h}`, `pipeline_shader_emission.h` | `0x6a7df2967675ba5a` | `0x69492cec5635d4cb` |

(Read from `build/…/generated/video_core/shader_cache_v2/lowering_stamp.h` and `shader_warm/emission_stamp.h` of the
two build trees.) They differ because upstream changed `frontend/ampere/lower_to_maxwell.h` (+134 −65) and nine more
recompiler files, among them `spirv_emit_context.cpp` (+63, #2103 and #2162: how bound buffers are searched on the
select path, in task and mesh programs too) and `emit_spirv_mesh.cpp`.

What a build does with a file stamped by another build:

- **Program records** (`vk_pipeline_cache.cpp:1511–1574`, `shader_cache_v2/cache.cpp:80–130`): every `Program` record
  whose stamp is not this build's is lowered again at boot ("programs of another build lowered again"), rewritten
  with this build's stamp, and the pipeline records of programs whose lowered code or texture bound buffer changed
  are moved to the new code (the old ones get tombstones). The next boot of the *other* build then finds all program
  records stale and does the same in reverse.
- **Precache** (`vk_pipeline_cache.cpp:2009–2045`, `WarmVariant`): the marker beside `warm-compute.bin` holds a hash
  that includes `EmissionStamp`. With "precache shaders" on, a build with another stamp builds the file's compute
  programs again and rewrites the marker; the other build then does the same. (The user's config has
  `precache_shaders=0`; what that value selects was not looked up.)
- **SPIR-V**: the disk cache holds guest code, not SPIR-V (`pipeline_cache_files.h:23–29`); each build emits its own.
  Where the new emitter produces different SPIR-V for a shader, MoltenVK's pipeline cache has no entry for it and
  translates and compiles it again, and Metal's own cache
  (`$(getconf DARWIN_USER_CACHE_DIR)/io.github.zortos293.lichii/com.apple.metal`, per bundle id, about 1 GiB) gets a
  second copy. How many of the game's shaders change is not known without running; #2103/#2162 change the buffer
  search that most native programs use, so it may be most of them.

### Answer

**Running this build on the installed build's data directory would not delete its caches for a version mismatch, but
it would rewrite them**: all program records restamped (and re-lowered again by the installed build at its next
boot), pipeline records possibly moved, the precache marker replaced, `vulkan_pipelines.fork-v54.bin` saved again
from a session of the new build, and new entries pushed into the shared 1 GiB Metal cache. It would also rewrite
`qt-config.ini` (new key `nextendo_kept_accounts`, a 35th default hotkey). Whether the installed build would then
have to translate every shader again was not measured and cannot be ruled out from the code. **Do not run it on the
shared directories.**

### Running it without touching the installed build's caches

How the data directory is chosen (`src/common/fs/path_util.cpp:114–160`, `Reinitialize`, unchanged between the
bases; names in `src/common/fs/fs_paths.h`: `PORTABLE_DIR "user"`, `EDEN_DIR "lichii"`, `CACHE_DIR "cache"`,
`CONFIG_DIR "config"`, `SHADER_DIR "shader"`):

1. **Portable mode:** if `<current working directory>/user` exists and is a directory, everything lives in it: data
   in `user/`, cache in `user/cache/`, config in `user/config/`. On macOS it is the working directory, not the
   binary's folder (the binary's folder is used on Windows only). A Finder or `open` launch has `/` as its working
   directory, so this needs a direct start of the binary with `cwd` set.
2. **Otherwise** `XDG_DATA_HOME`, `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` (absolute paths only,
   `GetDataDirectory`, line 383), each with `/lichii` appended; unset, they are `~/.local/share`, `~/.cache`,
   `~/.config`. These work for any kind of launch, including through `LSEnvironment` in the app's `Info.plist`.

The config file can redirect individual folders (`src/frontend_common/config.cpp:384`), so a copied `qt-config.ini`
must be checked for absolute paths into `~/.local/share/lichii`.

The Metal cache is not under either: it is per bundle id, so full isolation also needs a bundle id of its own, as
`wip/shader-prebuild` did.

A private setup that starts warm and leaves the installed build alone (not run here):

```bash
P=$(git rev-parse --show-toplevel)/build/next/data     # private root
mkdir -p "$P/share/lichii" "$P/cache/lichii/shader" "$P/config/lichii"
cp -Rc ~/.local/share/lichii/keys ~/.local/share/lichii/nand ~/.local/share/lichii/load "$P/share/lichii/"
cp -c  ~/.config/lichii/qt-config.ini "$P/config/lichii/"
cp -Rc ~/.cache/lichii/shader/0400486024dec000 "$P/cache/lichii/shader/"            # 570 MB, a copy: the original is not touched
# then launch with XDG_DATA_HOME=$P/share XDG_CACHE_HOME=$P/cache XDG_CONFIG_HOME=$P/config
```

Copy the shader folder while no Lichii is running (the installed build's files were last written 2026-11-19 04:40).
The copies are APFS clones (`-c`) and take no space until changed. With the pinned MoltenVK library in the test app,
the copied `vulkan_pipelines.fork-v54.bin` is accepted (same `pipelineCacheUUID`), so the first boot costs the
re-lowering pass plus whatever SPIR-V changed, in the private copy only. With its own bundle id the test app also
starts from an empty Metal cache (about 100 s for the pinned build with the pipeline file kept); with the installed
build's bundle id it shares, and adds to, the installed build's Metal cache.

## Build

| | |
| --- | --- |
| Result | **Succeeded**, first attempt, 0 errors: configure and `cmake --build build/release --target lichii` with exactly `build.sh`'s `step_lichii` flags, 1,879 steps, about 6 minutes with ccache |
| Binary | `build/next/lichii/build/release/bin/lichii.app/Contents/MacOS/lichii`, 51,921,072 bytes, sha1 `ad684721901a96e417a6a63be588adbe7ddf41df` |
| Logs | `build/next/logs/lichii-configure.log`, `lichii-build.log` |
| Tools | as `versions.lock` lists (same machine) |
| In the binary (`strings`, not run) | `P60_HMMA_MEM`, `P60_UINT8_HOST`, `P60_LIST_INDIRECT`, `P60_OOT_BILINEAR`, `P60_RUN_AHEAD`, `P60_SYNC_TRACE`, `EDEN_NX2_SHARED_JIT_CACHE`, `EDEN_NX2_JIT_FLUSH_ON_STALL`, `EDEN_NX2_MESH_TG_LIMIT`, `EDEN_NX2_STUTTER_ALL_FRAMES`, `DYNARMIC_JIT_TRACE`, `jit_clear` |

No Lichii binary was executed. `build/src/`, `build/app/`, `patches/lichii/`, `patches/moltenvk/`, `versions.lock`,
`build.sh` and the user's Lichii folders were only read.

A note for anyone repeating the clone: `build/src/lichii` is a partial clone whose config has lost its promisor
settings, so a plain `git fetch` in it or in a copy fails with "pack has 1 unresolved delta". In the copy,
`git config remote.origin.promisor true` and `git config extensions.partialClone origin` make the fetch work.

## Tests

- **`dynarmic_tests`: 144 of 144 cases pass** (201,983 assertions), also with 2 MiB code regions
  (`DYNARMIC_ARM64_REGION_SIZE=2097152`). Built from `gold-next` in `build/next/lichii/build/jit` with the configure
  line of `tools/jit-cache/README.md` (RelWithDebInfo, asserts on); binary `build/jit/bin/dynarmic_tests`, log
  `build/next/logs/dynarmic_tests.log`. These run the arm64 backend as changed by the shared-cache patch, each JIT
  with a private cache.
- **`jit_shared_cache_tests` does not exist in this tree**, and neither do the two extra `dynarmic_tests` cases
  (block table, JIT replay) that made 146 in `research/shared-jit-cache/`: all of them live in
  `patches/upstream/dynarmic-pr2101-tree-shared-jit-cache-with-tests.patch`, which is cut for the PR #2101 tree. So
  several cores on one shared cache were **not** tested on this base. The dynarmic sources are byte-identical to the
  pinned ones, which those tests covered; the Lichii-side glue differs by the one change described above.
- Lichii's own test target (`tests`, which has `mesh_fallback.cpp` and `mesh_vertex_input.cpp`) was not built.
- Nothing was run in the emulator.

## Assembling a test app (not run here)

The same steps as `build.sh`'s `step_app`, with the pinned MoltenVK library taken from the assembled pinned app
(sha1 `bd4459df630850d8165e99b0192d15eeb216ac75`, pipeline cache id `04ac9bef`), into a folder of its own:

```bash
R=$(git rev-parse --show-toplevel)
N=$R/build/next
P=$N/data
app=$N/app/lichii.app
mkdir -p "$N/app"
ditto "$N/lichii/build/release/bin/lichii.app" "$app"
cp -p "$R/build/app/lichii.app/Contents/Frameworks/libMoltenVK.dylib" "$app/Contents/Frameworks/libMoltenVK.dylib"
{ cat "$N/lichii/dist/nx2_switches.txt"; printf '\n'; cat "$R/config/nx2_switches.append.txt"; } > "$app/Contents/MacOS/nx2_switches.txt"
# its own Metal cache (leave this line out to share the installed build's Metal cache)
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier io.github.zortos293.lichii.next' "$app/Contents/Info.plist"
# launch environment for Finder / open: the pinned app's line plus the private data directory
/usr/libexec/PlistBuddy -c 'Add :LSEnvironment dict' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :LSEnvironment:MVK_P60_NO_APPNAP string 1' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:XDG_DATA_HOME string $P/share" "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:XDG_CACHE_HOME string $P/cache" "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSEnvironment:XDG_CONFIG_HOME string $P/config" "$app/Contents/Info.plist"
codesign --force --sign - --preserve-metadata=entitlements "$app"
shasum "$app/Contents/MacOS/lichii" "$app/Contents/Frameworks/libMoltenVK.dylib"
```

`LSEnvironment` applies only to launches through Finder, the Dock or `open`. A harness that starts the binary
directly must export the three `XDG_*` variables itself (or start it with a working directory that holds a `user`
folder); without them it uses, and rewrites, the installed build's folders.

Before the first run, check in the private `qt-config.ini` that no path setting points into
`~/.local/share/lichii`.
