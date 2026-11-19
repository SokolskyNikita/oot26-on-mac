# nxnative as a platform for glitch research

An evaluation of [seedds/nxnative](https://github.com/seedds/nxnative), done by reading only. Nothing from it was
cloned, built, downloaded or run. Everything below was read on 2026-11-16 through `gh` (files, issues, PRs,
discussions, commits) at `main` = [`edc7eff9`](https://github.com/seedds/nxnative/commit/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d)
(committed 2026-11-16 19:33 UTC), unless a line gives another date.

The repository changes many times a day, so links to files point at that commit.

How claims are marked:

- Plain text is what the project or its users **state**, with a link.
- *Inferred:* marks this evaluation's own conclusions. None of them has been tested.

The background is [`../moltenvk-offramp/README.md`](../moltenvk-offramp/README.md), section 5, which found the project.
Lichii's setup is described in [`../../config/README.md`](../../config/README.md). The evaluation asks whether
nxnative could replace Lichii for glitch research on the game: debugger breakpoints on game code, scripted input,
the sloperinaGZ practice mod, frame-exact repeats. The tools named for that work (`jsdbg.py`, a DSU pad server, a
list of jumpslash addresses) belong to a separate glitch-research repository and are not in this one.

**Short answer:** **wait**, but keep watching. nxnative gives lldb on game code at `main+offset`, frame-stamped
scripted input and a deterministic clock. It cannot load sloperinaGZ, and it has no frame advance and no savestates.
Trying it would mean installing Xcode 27.2, finding about 60 GB of disk, and running a large codebase from one
author that nobody has reviewed, three committed prebuilt binaries included. Section 5 lists what would change the
answer.

---

## 1. What it is and how it works

**What it says it is.** The [README](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/README.md) describes nxnative as a way to play your own Switch and Switch 2
games on Apple silicon Macs, iPhones and iPads. It states that it is not an emulator: the game's own code runs
directly on the Apple chip, and Switch graphics are rebuilt on Metal. A script packs a game into a Mac app or an
unsigned IPA. OoT is one of 15 Switch 2 games listed as having "passed Mac gameplay testing".

**How game code runs.** The [development guide](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/development.md), "How it works", says:

- An offline **rewriter**, `dm/tools/patch_nso.py`, rewrites each code module (`main`, `subsdk0` and `sdk` for OoT)
  before the game runs.
- A **host**, `dm/host`, stands in for the Horizon kernel and system services: threads, memory, files, HID, audio
  and movies.
- The rewritten modules are loaded into the host process at a module base and run natively.
  [`loader.c`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/host/loader.c) relocates them the way Horizon's rtld would, and resolves imports against the
  other modules, then against the host's own HLE functions.

The rewriter changes only specific instructions. [`rewriter.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/reference/rewriter.md), "Thread registers",
says why: the guest's `x18` lives in a per-thread memory slot, because the Apple kernel may change the register
at any instruction, so every instruction that uses `x18` is rewritten to load or store that slot. Other changes:

- system-register reads, `svc` calls and counter reads, through gates;
- jump tables;
- spin-wait loops;
- per-game cuts and stubs from the profile's `patches.py`.

Code that needs more room branches into a **patch area** beside the module. Every word changed or moved is listed in
`main.changed.tsv` and `<module>.cuts.tsv` (development guide, "Cheats", and `rewriter.md`).

**How NVN and shaders reach Metal.** Stated in the development guide and the [third-party list](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/third_party/README.md):

- NVN is reimplemented on Metal in `dm/gfx/nvn`.
- Shaders are taken from the game's containers by `shader_split.py`. Ryujinx's shader library (1.3.2, MIT, with
  local fixes) translates them to SPIR-V, and SPIRV-Cross turns that into Metal Shading Language. Xcode 27.2's
  Metal compiler builds the result offline.
- OoT's task and mesh shaders become Metal object and mesh functions, with no Vulkan in between. That was recorded
  in `../moltenvk-offramp/README.md` §5 from
  [`shaders.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/reference/shaders.md).
- The [OoT note](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/games/0400486024DEC000/README.md), "Shaders", counts about 42,850 shaders in the game, 500 of
  them mesh and 20 task shaders.

**Requirements** (README, "Requirements" and "Build from the command line"):

- An Apple silicon Mac on macOS 26.6 or later. The test Mac (Apple M4 Pro, Mac16,8) runs 27.0.1.
- To build: Xcode 27.2 selected with `xcode-select`, its Metal toolchain (`xcodebuild -downloadComponent
  MetalToolchain`), Homebrew's `xcodegen`, `zstd` and `glslang`, and an arm64 Python 3.12+ with `lz4`,
  `capstone>=5,<6`, `fonttools`, `nsz`, `zbic` and `backports.zstd`.
- The build script refuses the Command Line Tools as the developer folder for an iOS build
  ([`build_ipa_from_nsp.py`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/scripts/build_ipa_from_nsp.py), line 1290). The Mac shaders need Xcode's Metal
  compiler in any case.
- The first build takes 30–60 minutes and needs free disk of about twice the game's size plus 10 GB.

**How the game is supplied.** A Switch 2 game is given as one `.nup` file, or as a folder laid out as
`base/exefs`, `base/romfs`, `updates/<version>/…` and `dlc/…`. Neither needs `prod.keys`; only NSPs do (README,
"Switch 2 games"). The dump used for this project is a single NUP (the base game plus update v131072), which is the input it
expects.

- A bug with bracketed folder names, which dropped OoT's patches silently, was fixed after
  [PR #1826](https://github.com/seedds/nxnative/pull/1826) (`rewriter.md`, "Repository patches missing under
  bracketed paths").
- The OoT profile pins update v131072 with `main` build `e0f3ccfaf50065ae…`
  ([`game.tsv`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/games/0400486024DEC000/game.tsv)). That is the same `main` the Lichii setup here records,
  `E0F3CCFA…`.
- For playing, `--platform mac-app` gives a double-clickable app. For development, `--platform mac` builds only the
  host, the rewritten modules and the Mac shader libraries, and prints the command that runs the game (development
  guide, "A Mac-only build for development").

**Licence and credits.** MIT ([LICENSE](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/LICENSE)). Third-party code keeps its own licence: dav1d, libvpx,
stb_vorbis, Ryujinx's shader library, Vulkan headers, NVIDIA FLIP, plus pieces of deko3d and MacNativeGames. The
README says the project began as a copy of the generic parts of
[jhaizhou-ops/d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile), which is MIT, was created 2026-10-12 and has
about 5.3k stars. The owner also has a repository of that name, created the same day.

**Who maintains it, and how active it is** (`gh`, 2026-11-16):

| | |
| --- | --- |
| Owner | `seedds`, a personal account created 2013, no name, bio or company, 51 public repos, 202 followers |
| Created | 2026-10-13. The first commit, 2026-10-12, boots Mario Wonder on the Mac host |
| Commits | 1,706 on `main` in five weeks, about 50 a day. 1,642 are credited to `seedds`, and every one of the last 100 was committed by `seedds` |
| PRs | 30 merged, 844 open, 1,101 closed unmerged. Commit messages cite PR numbers, so *inferred:* the owner re-lands contributors' work as their own commits instead of merging it |
| Issues | 811 issues, 1,251 open issues and PRs together, 133 issues naming OoT's title ID (81 open). Discussions are on |
| Popularity | about 15.9k stars and 2.9k forks |
| Releases | none, and no tags. You build from source |

*Inferred:* the volume of code and prose, its uniform style and the agent-oriented docs
([`AGENTS.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/AGENTS.md), [`docs/agents/`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/agents/README.md)) suggest that most of it is written with AI
tools. That is not a defect in itself, but it means very little of this code has had a human review.

## 2. How credible the 60 fps claim is for this game

**What was measured.** The [OoT note](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/games/0400486024DEC000/README.md), "Frame rate", whose latest change is
2026-11-16 (`edc7eff9`), states:

- **Headline run:** an M5 Pro MacBook Pro (20-core GPU, 24 GB, macOS 27.2), 2026-11-09, on the `kokiri-deck` bench
  route ([`bench.tsv`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/games/0400486024DEC000/bench.tsv)):
  - The route loads a Kokiri Forest deck autosave, stands 20 s, turns the camera and walks for a 45 s window.
  - Full resolution, dynamic resolution off, the full shader library, two runs per variant.
  - In a window: a locked 60 fps (59.8–60.0), frame p99 16.8–19.4 ms, GPU p50 10.2 ms.
  - Fullscreen on the ProMotion screen held only 40 fps until the screen was switched to a fixed 60 Hz mode, which
    gave 60.0 fps.
- **The chip used here, the M4 Pro (20-core GPU):**
  - 2026-11-08, with a partial shader set: 51.8 fps, GPU p50 12.6 ms, 60 fps "most of the time".
  - 2026-11-09, a three-run bench of a shader-translator change on `kokiri-deck`: 54.0 → 59.1 fps.
  - Later contributor runs at graphics-scale tier 0, docked and fullscreen: 55.8–59.8 fps.
  - Owner's [discussion #1789](https://github.com/seedds/nxnative/discussions/1789), 2026-11-08, at full resolution:
    about 48 fps. The GPU "often holds 30 for stretches".
- Several runs are credited to an "M6 Mac" with 16 GB. *Inferred:* that chip name could not be placed, so those
  numbers are treated as unverified.
- **How far the note goes:** the title, the opening, a new file's first scene, Link's house and Kokiri Forest.
  It says the Deku Tree dungeon, combat and later areas are "not played yet", and that physics issues reported
  in PR 1299 were not seen on its route.

So the claim is narrow: **one route of about a minute in Kokiri Forest, at about 60 fps on recent Pro-class
GPUs**. Elsewhere the same note reports:

- 9–12 fps in Castle Town on a first visit, later fixed to frame p50 16–28 ms;
- frames of 100–650 ms when an area first loads (open);
- a first start with a cold shader cache that took minutes (issue
  [#1477](https://github.com/seedds/nxnative/issues/1477));
- a pipeline prebuild of 691 s the first time a new shader chain is used.

**Known breakage for this title** (the note's "Open" section and the issue tracker):

- **GPU hangs** ending in "GPU access revoked", mostly on M1 and M2 Pro/Max:
  [#1326](https://github.com/seedds/nxnative/issues/1326) (took WindowServer down),
  [#1986](https://github.com/seedds/nxnative/issues/1986), [#2011](https://github.com/seedds/nxnative/issues/2011),
  and [#2777](https://github.com/seedds/nxnative/issues/2777) (GPU firmware lockup and restart on an M1 Max).
- **Memory:** about 10–11 GB resident in play. Before the fixes the game caused a kernel panic in
  `IOGPUGroupMemory` at 14.7 GB wired (the note's "Memory" section). Also
  [#2068](https://github.com/seedds/nxnative/issues/2068) (GPU memory 3 → 13 GB in a minute, closed) and
  [#2680](https://github.com/seedds/nxnative/issues/2680) (Metal archive folders piling up to hundreds of GB,
  closed).
- **Slow states that last until a restart:** [#2277](https://github.com/seedds/nxnative/issues/2277),
  [#2629](https://github.com/seedds/nxnative/issues/2629), [#2751](https://github.com/seedds/nxnative/issues/2751).
- **On M4 Pro:** [#1747](https://github.com/seedds/nxnative/issues/1747) (about 5 minutes of shader preparation on
  every start, including warm ones) and [#2088](https://github.com/seedds/nxnative/issues/2088) (visual errors
  after about 4 h).
- **Rendering differences, open:** pale halos, white flashes, missing walls in the Water Temple, invisible Fire
  Temple platforms ([#1767](https://github.com/seedds/nxnative/issues/1767)), and Lens of Truth artefacts.

**What independent users report.** Many users report progress well past what the note covers, on several Macs:

- [#1767](https://github.com/seedds/nxnative/issues/1767): an M3 Max played through the Fire Temple, one session of
  5 h 37 m with no crash. Some geometry was invisible but its collision worked.
- [#2824](https://github.com/seedds/nxnative/issues/2824): an M5 Air played from Ganon's Castle to the credits,
  4 h 39 m, exit 0, on a week-old build.
- Discussion #1789, 2026-11-15: a Mac mini M4 (10-core GPU, 16 GB) held frame p50 16.6–16.8 ms for 75 minutes. An
  M2 Max got 30 fps docked and about 60 handheld with MetalFX.

*Inferred:* the 60 fps figure is credible for Kokiri Forest-class scenes on M4 Pro and newer, with margin only on
M5-class GPUs. It is not a whole-game guarantee. On the M4 Pro, expect roughly 50–60 fps in open areas. The game
is playable to the end, but with rendering defects and a real chance of GPU hangs. Note too that every issue
title and body has the project's own documentation style, so some "independent" reports may themselves be
AI-assisted.

## 3. Fit for glitch research

| Need | Status | Evidence |
| --- | --- | --- |
| lldb breakpoints on game code at `main+offset` | **Yes, with caveats** | below |
| Fixed 1/60 s game step | **Not by default; can be configured** | below |
| Scripted input | **Yes, but not DSU** | below |
| sloperinaGZ (`subsdk9` plus `.ips`) | **No** | below |
| Lichii save compatibility | **Not documented** | below |
| Frame advance or savestates | **Not found** | below |

**lldb.** [`05-debugging.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/agents/05-debugging.md), section "lldb", gives a working template:

- The target is the host binary, `dmhost`, launched on the rewritten-modules folder.
- Break on `run_module_inits`, read `g_mod[0].base` (the base of `main`), then set breakpoints at `base +
  offset`.
- SIGSEGV, SIGBUS, SIGUSR1/2 and SIGPIPE must be passed through, because the host uses SIGSEGV to track dirty
  pages, and `EXC_BAD_ACCESS` is set as ignored.
- Address randomisation is off under lldb, so guest addresses repeat from run to run.
- Hardware watchpoints on words touched by `ldxr`/`stxr` may stay silent.
- Without a debugger, [`DM_PROBE`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/agents/05-debugging.md) puts a `brk` at `module:offset` and logs
  registers and a backtrace. `DM_PROBE_WATCH` logs who writes a word, and `DM_PROBE_POLL` snapshots threads when a
  word changes.
- The OoT note and [`patches.py`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/games/0400486024DEC000/patches.py) name functions as `main+0x…` on v131072,
  in the same terms as the glitch-research notes. One example: the frame-ratio division at `main+0x6e6cc4`, which `patches.py` says
  Lichii's notes found.

*Inferred:* `main+offset` addresses from Lichii keep their meaning for most instructions. The exceptions are the words the
rewriter changed, which `main.changed.tsv` lists:

- every instruction that touches `x18`;
- `svc` calls and system-register reads;
- jump-table dispatches and spin-wait loops;
- OoT's six stubs and cuts.

At those addresses a breakpoint lands on a branch into the patch area, not on the original instruction. Before
porting a breakpoint, its offset has to be checked against that file. There are other differences too:

- There is no GDB stub: lldb debugs the host process itself, so the Lichii debugger scripts
  (`jsdbg.py`, `boot_manual.sh`) would need rewriting.
- Heap addresses will differ from Lichii's, although the project says they are stable from run to run.
- Breakpoints stop the whole host. Its watchdogs and its GPU submission may react to long stops; that is not
  documented either way.

**Timing.** `patches.py` describes what the game does on its own: it advances time by a fixed ratio each frame,
the base rate (60, or 30) divided by its frame rate, whatever the frame actually took. A frame that takes two
vsyncs therefore plays in slow motion. *Inferred:* that matches what is seen under Lichii.

nxnative changes this by default:

- OoT's profile sets `fps_target 60`. The rewriter then stubs that division to use the host's frame step instead,
  `step × base / 60`.
- A late frame (a hold of 2 or 3 vsyncs) therefore advances game time by 2 or 3 steps, so game time keeps up with
  real time.
- With `DM_FPS_TARGET=0`, the game's own division runs. `patches.py` says so ("at fps_target 0, the division
  runs"), and [`docs/env_switches.tsv`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/env_switches.tsv) describes `0` as "the game's own limit".
- `DM_DETCLOCK=<step ns>` advances the guest clock by a fixed step per present instead of following the wall
  clock, and replaces the random source with a fixed-seed stream. `DM_DETCLOCK_PACE=1` makes each frame take at
  least one step of wall time.
- The movie cuts in `patches.py` change only the movie player.

*Inferred:* glitch research would run with `DM_FPS_TARGET=0` plus `DM_DETCLOCK`, to get one fixed step per game
frame and reproducible random numbers. That combination is not documented for OoT and has not been tested by
anyone found.

**Inputs.** No DSU or cemuhook server was found; the host reads physical controllers through GameController and raw
HID. Scripting goes through environment switches instead ([`05-debugging.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/agents/05-debugging.md),
"Scripted input"; development guide, "Recording input"):

- `DM_KEYS` presses buttons, sticks at full tilt or at values, touches and shakes, at seconds or at presented-frame
  numbers (`f2500:A`). Holds can be given in frames (`~f12`).
- `DM_CTL=<file>` takes commands appended to a file while the game runs, polled every 100 ms:
  - a press, or `P2 A` for player 2;
  - `shot <path>`;
  - `peek <address> <count>` and `memdump <address> <bytes> <path>`;
  - `env KEY=VALUE`.
- `DM_REC` records player 1's input as frame-stamped `DM_KEYS` steps. Replayed with the same build, the same save
  copy and the same `DM_DETCLOCK`, the project says it matches the recording read for read.

*Inferred:* the glitch-research repository's DSU pad server would not plug in. A small adapter that writes `DM_CTL` lines would
replace it. Frame-stamped `DM_KEYS` is a better fit for repeatable glitch setups than real-time DSU packets.

**sloperinaGZ.** Not supported on `main`:

- Code mods are open proposals or open PRs, none merged:
  - [#1133](https://github.com/seedds/nxnative/issues/1133): load exlaunch `subsdk9` plugins (issue);
  - [#2294](https://github.com/seedds/nxnative/issues/2294): IPS, IPS32 and `.pchtxt` exefs patches at build
    time (issue);
  - PR [#2297](https://github.com/seedds/nxnative/pull/2297): the same, as a `--exefs-patches` build option;
  - PR [#2149](https://github.com/seedds/nxnative/pull/2149) and PR
    [#2150](https://github.com/seedds/nxnative/pull/2150): emulator mod folders, then rewriting refused code
    patches at launch;
  - PR [#883](https://github.com/seedds/nxnative/pull/883): mods support;
  - PR [#2305](https://github.com/seedds/nxnative/pull/2305): OoT LayeredFS.
- The profile's `modules` line is `main subsdk0 sdk`.
- What works today: Atmosphère-format **cheats**, with a Mac menu and a dry run (development guide, "Cheats"), and
  **RomFS overlays** (`DM_ROMFS_OVERLAY`). A cheat may not write over a word the rewriter changed.

*Inferred:*

- sloperinaGZ's `.ips` files target the same `main` build, so PR #2297 would probably carry them once merged.
- Its `subsdk9` is a separate problem. It would have to go through the rewriter, and its exlaunch hooks patch
  `main` at run time, which this host would have to allow.
- Until then, sloperinaGZ's functions (setting items, flags and positions) would have to be rebuilt as cheats or
  as `DM_CTL` memory writes.

**Saves.** The OoT note's "Saves" section lists the game's own files, kept in the folder named by `DM_SAVE`
(committed transactionally, with a `<DM_SAVE>_device` beside it):

- `slot_00` and `slot_01`, the autosaves;
- `option.sav` and `account.sav`;
- `caption.sav`, the thumbnails.

Import from emulators is not documented. [#2420](https://github.com/seedds/nxnative/issues/2420), open, proposes it,
building on [#921](https://github.com/seedds/nxnative/pull/921), also open. The only documented copy is from one
nxnative install to another ([`playing.md`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/docs/playing.md)). *Inferred:* both programs store the game's own
save files, so copying Lichii's files into `DM_SAVE` will probably work. It has not been checked.

**Frame stepping and snapshots.** Not found:

- `DM_CTL` has no pause or step command, and nothing in `env_switches.tsv` adds one.
- No issue or PR mentions savestates or frame advance.
- The nearest substitutes are replays (`DM_DETCLOCK` plus `DM_REC`, started from a copy of the save) and GPU frame
  capture and replay, which covers rendering only (development guide, "Frame capture and replay").
- An lldb breakpoint can still freeze the game on a chosen instruction, as under Lichii.

## 4. Safety and trust

**What building it runs:**

- Python scripts, `make`, clang, Xcode's Metal compiler, and `codesign` (ad hoc by default).
- `sudo` once, for `xcode-select`.
- Packages from Homebrew and PyPI (section 1).
- Three **prebuilt executables committed to the repository**, which the build runs: `dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate`
  (7.9 MB, the C# shader translator compiled with NativeAOT), `dm/tools/nx_extract_bin/nx_extract` (4.8 MB) and
  `dm/gfx/tools/spirv_cross_bin/spirv-cross` (6.1 MB). The development guide ("Build by hand", and the
  `native_tools.sh` row of "Tools") says the first two can be rebuilt from source with the .NET SDK 10 via
  `dm/tools/native_tools.sh`. `spirv_cross_bin/` holds a `build.sh` beside its binary. `dmsh_xlate` was changed 5
  times on 2026-11-14 and 2026-11-16 alone.
- No other blobs were found. The tree's other binary files are small fuzz-test inputs.

*Inferred:* to trust a build, you would rebuild those three executables from source, compare them with the
committed ones, and then use your own builds. A rebuild "has another fingerprint", so byte equality is not
expected, which makes that comparison weaker.

**What running it needs** ([`pack_app.py`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/mac/pack_app.py), lines 11–13 and 157–172):

- The app and its host are signed ad hoc, **without the hardened runtime**, because the host maps the game's code
  executable. As a result the app cannot be notarised.
- No entitlements are requested.
- No kernel extension, hypervisor, SIP change or system-setting change was found.
- `MAP_JIT` is used only for `nn::jit`, which OoT does not use ([`hle_jit.c`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/host/hle_jit.c)).
- lldb needs developer mode (`DevToolsSecurity`), as the debugging guide says.

*Inferred:* the host runs as an ordinary unsandboxed user process. It can read everything the user can, and it
also runs game code natively in the same address space. The risk is in the host's code, not in any special
privilege it asks for.

**Network:** [`hle_net.c`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/host/hle_net.c) says network services stay offline. Socket and network-manager
initialisation are stubbed, and only process-local UDP and eventfd transports exist. Save sync through iCloud
Drive is off unless `DM_SAVE_SYNC` names a folder ([`save_sync.h`](https://github.com/seedds/nxnative/blob/edc7eff9cf9d1e4b2134c624e2b8cb690b0e586d/dm/host/save_sync.h)). The only URL in the
build script is the project's issue page. The build fetches nothing besides what Homebrew and pip install.

**What gives pause:**

- One account wrote and committed nearly all of more than 1,700 commits in five weeks.
- Contributors' PRs are re-landed as the owner's own commits (section 1), so history shows little about who wrote
  what.
- Prebuilt executables change often.
- The project's own notes record the game crashing the Mac: a kernel panic in `IOGPUGroupMemory` before a fix,
  GPU hangs that took WindowServer down (#1326), and GPU firmware restarts (#2777).
- Memory use is about 10–11 GB resident, and Metal's caches have grown to hundreds of GB (#2680).

*Inferred:* that history is more of a stability risk to the machine and to other work running on it than a sign
of malice. Nothing that looks malicious was found, but nobody could read this volume of code by eye.

## 5. What trying it would take, and a recommendation

**Steps** (*inferred* from the README and development guide, none of them run):

1. **Xcode 27.2.** Install it (a large download, from Apple's developer site), select it with `sudo xcode-select
   -s`, and run `xcodebuild -downloadComponent MetalToolchain`. The test Mac has only the Command Line Tools, so
   this step cannot be skipped. lldb from the Command Line Tools would still work.
2. **Tools.** `brew install xcodegen zstd glslang`, and the pip packages, in a separate virtual environment.
3. **Disk.** At least 60 GB on top of what is used now: about 2 × 25.6 GB for the NUP plus 10 GB, more for the
   pipeline archive and Metal caches. The test Mac's disk had 105 GB free (`df`, 2026-11-16). An external drive is supported
   but has its own reported problems: exFAT ([#2434](https://github.com/seedds/nxnative/issues/2434)), and the
   pipeline archive being read into memory.
4. **Review first.** Rebuild the three prebuilt executables from source (section 4) and read the host's
   process-level code: `loader.c`, `hle_svc.c` and `hle_fs.c`.
5. **Build** with `python3 scripts/build_ipa_from_nsp.py <the NUP> --platform mac`: 30–60 minutes the first time,
   then a shader prebuild of about 11 minutes with a window. Run under `DM_FPS_TARGET=0 DM_DETCLOCK=16666667`.
6. **Share the machine politely.** Hold the emulator lock (`tools/verify/verify.py with-lock`) while it runs. It
   loads the GPU and memory as heavily as Lichii and will skew other measurements.
7. **First checks, in order:**
   1. lldb breaks at a known function (for example the frame-ratio function at `main+0x6e6be0`) and at one of
      the glitch-research jumpslash addresses, after checking it against `main.changed.tsv`;
   2. a Lichii save copied into `DM_SAVE` loads;
   3. a `DM_KEYS` route reproduces frame for frame.

**Recommendation: wait.** It is too promising to ignore, but not worth trying yet:

- **For:** lldb on game code at `main+offset`, a deterministic clock with frame-stamped input and replay, and
  about 1.5–2× the frame rate of stock Lichii build 228 (25 fps standing). *Inferred:* against the pinned build in
  this repository (53–58 fps standing, 43–48 fps walking) and nxnative's own M4 Pro figures (48–59 fps), the gap is
  small or none.
- **Against:**
    - The main glitch-research tool, sloperinaGZ, does not load.
  - There is no frame advance, and no savestates (Lichii has none either).
  - The default time step differs from the game's own and has to be switched off.
  - It costs an Xcode install, about 60 GB of disk, and trust in a fast-moving single-author codebase with
    committed binaries.
- Most glitch-research work stops at breakpoints anyway, so the frame rate gain matters less there than to
  players. *Inferred:* the case for trying gets stronger only when long real-time runs are needed, such as visual checks,
  routes, or many repetitions of a setup.

**What would change the answer:**

- PR #2297 (exefs IPS patches) or PRs #2149/#2150 (mod folders) merged, or issue #1133 (exlaunch `subsdk9`)
  implemented, so that sloperinaGZ could load.
- A pause or frame-step command in `DM_CTL`.
- A need for real-time 60 fps runs that Lichii cannot give.
- Tagged releases, or a second maintainer, as a sign of steadier development.
