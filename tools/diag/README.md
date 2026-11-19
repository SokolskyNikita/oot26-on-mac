# diag: diagnostic capture

Every diagnostic switch of the pinned build and of the harness, what each one writes and costs, the readers of
their output, and harness specs that capture them. A capture is a harness run (`tools/harness/queue.sh SPEC.json`,
under the emulator lock) with switches in its spec's `env`; the readers here read the run folder afterwards and
never start Lichii.

| File | What |
| --- | --- |
| `switches.json` | The catalogue: one record per switch (fields below), and `not_diagnostic`, the behaviour and tuning switches the sources also read |
| `check_switches.py` | `python3 check_switches.py`: compares the catalogue with every environment name the pinned sources read (`build/src/lichii/src`, `build/src/moltenvk/MoltenVK/MoltenVK`, `patches/experiments/`), checks settings and debug calls against the sources, and this README against the catalogue; exits 1 when anything differs |
| `rundir.py` | The loader the readers share: a run folder or a batch folder, phases from `result.json`, the clocks below, frame-time bands, the walk check (`python3 rundir.py RUN…` prints each run's phases and frame statistics) |
| `frames.py` | `python3 frames.py [pct\|bands\|segments\|vi2] RUN…`: p50 / p90 / p95 / p99 / max per phase from `frames.bin`, frames per band, 300-frame segments, and Lichii's always-on 600-present lines by phase |
| `stutter.py` | `python3 stutter.py [slow\|segments\|split\|totals\|flushes\|all] RUN…`: the stutter trace by phase: slow frames and their causes with a class for each, walk segments with the 10 s summaries, where an ordinary frame's time goes (every-frame trace, repeats pooled by label), the cores' JIT totals at the end of the load and of the run, JIT flushes |
| `stats.py` | `python3 stats.py RUN…`: the periodic statistics lines of level 3a and the texture cache events, one block per kind, walking against standing |
| `gpu.py` | `python3 gpu.py [frames\|sync\|slow\|stalls\|gaps\|gapwaits\|gapctx\|perframe\|sigdiff] RUN…`: the frame profiler and the sync trace frame by frame; `sync` needs only `sync.txt` |
| `jit.py` | `python3 jit.py [log\|trace] RUN…`: the per-compile JIT log (`jit.bin`, experiment patch) and the code cache recording (`jit-trace.bin`) |
| `specs/` | Capture specs for the harness (below) |

All readers are standard-library Python 3 and take run folders (`tools/harness/runs/ab-…/LABEL`) or batch folders
(`tools/harness/runs/ab-…`, every run in it but the warm-up; `--with-warmup` keeps it). A folder from
`tools/verify/verify.py run` has another `result.json` and is refused. Every reader takes `--bands` (default
`20,22,26,33`: under 20, 20-22, 22-26, 26-33, 33 ms and over), `--log-clock` and, where it applies, `--phase`
(`stand1`, `walk`, `stand2`). A run with `variants` reads as one run per variant, labelled `LABEL/VARIANT`.

## Picking a capture

Start with the stutter trace on (every spec here has it): it costs nothing measured and it is what places log lines on
the harness clock. Then add one group per run, because the switches cost time and some of it lands on the frames
they explain.

| Question | Spec | Reader |
| --- | --- | --- |
| Is the walk slower, and where in it? | any (frames.bin is always there) | `frames.py` |
| Which slow frames compile JIT code, build pipelines or upload textures? | `specs/stutter.json` | `stutter.py`, `stutter.py split` |
| What an ordinary 20-26 ms frame (walk p95 is about 23-25 ms) spends | `specs/stutter.json` (every-frame lines) or `specs/gpu-side.json` | `stutter.py split`, `gpu.py frames` |
| Is the GPU busy or idle in slow frames, and waiting for what? | `specs/gpu-side.json` | `gpu.py frames`, `slow`, `stalls`, `gaps`, `gapwaits` |
| The same without the profiler's 46 MB | `specs/gpu-side.json` minus `MVK_FRAMEPROF` | `gpu.py sync`, `gpu.py slow` |
| Which guest threads use the frame, and what the JIT does per core | `specs/threads.json` (first entry) | `stats.py` |
| GPU front, back and worker time by zone | `specs/threads.json` (`diag-gpuprofile`, about 3 ms a frame) | `stats.py` |
| What the back waits for, present fences, timer lateness, core wake-ups | `specs/idle.json` | `stats.py` |
| Buffer and texture cache churn, read-backs of GPU-written memory | `specs/caches.json` | `stats.py` |
| What the JIT compiles during the walk | `specs/jit-trace.json` (445 MB file) | `jit.py trace` |
| Where the time goes on the CPU, stack by stack | `sample` on a running Lichii, outside the measured phases | `build/src/lichii/tools/nx2/macos_sample.py` |

The stutter trace has no per-frame line under 33 ms unless `EDEN_NX2_STUTTER_ALL_FRAMES` is set, so the walk's p95
frames (about 23-25 ms) are only seen with that switch or from the GPU side (`gpu-side.json`).

### The capture specs

Each entry walks 1,800 frames (`"phase_frames": 1800`) within 9 m of the Kokiri Forest spawn (`"leash_m": 9`),
stands 600 (`"stand_frames": 600`), has the stutter trace on, and says in `desc` what it tests (the emulator window
shows it). File-writing switches write under fixed names in the run folder (`{rd}/frameprof.txt`, `{rd}/sync.txt`,
`{rd}/jit-trace.bin`), which is where the readers look. None names an `app`, so they run the pinned build.

| Spec | Runs |
| --- | --- |
| `stutter.json` | A warm-up boot, then the every-frame stutter trace twice |
| `gpu-side.json` | `MVK_FRAMEPROF` and `P60_SYNC_TRACE`, twice |
| `threads.json` | `EDEN_NX2_GUEST_THREAD_STATS` with `EDEN_DKB_FRAME_TRACE`; `EDEN_NX2_GPU_PROFILE` on its own (its cost) |
| `idle.json` | `EDEN_NX2_BACK_IDLE_TRACE`, `EDEN_NX2_ACQUIRE_STATS` and `EDEN_NX2_PRESENT_FENCE_TRACE`; `EDEN_NX2_HOSTTIMING_STATS` with `EDEN_NX2_IDLE_STATS` |
| `caches.json` | `EDEN_NX2_DOWNLOAD_TRACE`; `EDEN_NX2_BUFFER_TRACE`, `EDEN_NX2_TC_TRACE`, `EDEN_NX2_DRAW_REUSE_PROBE` and `EDEN_NX2_TC_LOG` |
| `jit-trace.json` | `DYNARMIC_JIT_TRACE` |

```bash
cd tools/harness
./queue.sh ../diag/specs/gpu-side.json
python3 ../diag/gpu.py frames runs/ab-<date>-<time>       # every run of the batch
```

**The walk can stop.** A bounce walk that gets 14 m from the spawn can walk Link into an NPC's dialog near
(-6.6, 110.2, -11.5); he then stands for the rest of the walk and its frame times measure nothing. `"leash_m": 9`
kept him within 13 m in ten runs. Every reader prints a WARNING under a run whose `walk_call.path` has more than
two chunks in a row under 0.3 m apart (`rundir.Run.walk_stalls`).

## Where a switch can be set

| Where | What it takes |
| --- | --- |
| Process environment (`env` of a harness spec, `{rd}` = the run folder) | Every switch |
| `nx2_switches.txt` (beside the binary, and in Lichii's config folder) | Only `EDEN_NX2_*` and a short allow-list (`src/lichii/nx2_switches.h`, `LoadNx2Switches`): `EDEN_DKB_FRAME_TRACE`, `EDEN_DKB_INDIRECT_READBACK`, `EDEN_NATIVE_DRAW_CAPTURE`, `EDEN_NATIVE_DRAW_DIAGNOSTICS`, `EDEN_NATIVE_FRAME_CAPTURE`, `EDEN_NATIVE_SHADER_OVERRIDE_DIR`, `EDEN_PUNCH_HOLE`, `EDEN_STARFOX_WINDOW_TRACE`, `EDEN_VI2_MAX_RESOLUTION_MODE`, `EGLANTINE_EXPERIMENTAL_STATIC_VERTEX_REPACK`, `EGLANTINE_TEST_VERTEX_REPACK`. A variable already in the environment wins. `MVK_*`, `P60_*`, `DYNARMIC_*` and `MTL_*` can only be set in the process environment |
| `LSEnvironment` in the app's `Info.plist` (`config/launch-env.txt`, written by `build.sh`) | Any variable, for launches through Finder, the Dock or `open`; a binary started directly, as the harness does, ignores it |
| A debug-server call (`server_calls` in a spec, or `tools/harness/dbg.py`) | `host_timing`, `log_filter`, `frame_times`, `trace_record` / `trace_stop` / `trace_status`, `capture_frame`, `capture_bundle`, `sample` |
| A setting (`cfg` in a spec: a `qt-config.ini` key) | `record_frame_times`, `log_filter`, `flush_line`, `extended_logging`, `use_gdbstub` |

The harness itself sets `MVK_P60_NO_APPNAP=1`, `EDEN_NX2_DEBUG_SERVER` and `EDEN_NX2_DEBUG_DIR={rd}/dumps` on every run.

## Clocks

| Source | Clock | Unit |
| --- | --- | --- |
| `eden_log.txt` timestamps (`[   12.345678]`) | `steady_clock` since Lichii's logger started | s |
| `frames.bin` | `CLOCK_UPTIME_RAW` (`mach_absolute_time`) | ns |
| `P60_SYNC_TRACE` (`sync.txt`) | `CLOCK_UPTIME_RAW` | ns |
| `MVK_FRAMEPROF` (`frameprof.txt`) host times and command buffer GPU times | `mach_absolute_time`, the same clock as `frames.bin` | us |
| `result.json` `t_uptime` / `t_monotonic` | `CLOCK_UPTIME_RAW` / `CLOCK_MONOTONIC_RAW` of the same harness steps (start, boot_done, loading, in_game, load_done, settled, walk, stand2, end) | ns |
| `Nx2Boot … mono_s=` (stutter trace) | `CLOCK_MONOTONIC_RAW` (libc++'s `steady_clock`), with the line's log time | s |
| `EDEN_NX2_JIT_LOG` (`jit.bin`) | `CLOCK_MONOTONIC_RAW` | ns |
| `DYNARMIC_JIT_TRACE` (`jit-trace.bin`) | `steady_clock` from its first record; `jit.py trace` places it by the log's `JIT totals` lines | ns |

The two kernel clocks differ by the time the Mac has slept since it booted (hours on a laptop), so they are never
compared directly: `result.json` has both for every step, and their difference converts one to the other. Log time
maps to `CLOCK_MONOTONIC_RAW` through the `Nx2Boot` line, which exists only with the stutter trace on. Without it the
readers take `t_monotonic["start"]` as log time 0, which is about 0.25 s off (Lichii starts its logger after the
harness's mark), and say so under the run's header; `--log-clock start` forces that.

## The catalogue

`switches.json` holds one record per switch: `name`; `owner` (`lichii`, `ours-lichii-patch`, `moltenvk`,
`ours-moltenvk-patch`, `dynarmic`, `apple`, `harness`); `level` (below); `kind` (`env`, `setting`, `debug-call`,
`always-on`, `tool`); `purpose`; `output` (the log line prefix or the file); `granularity`; `cost` (a measured
figure with its source, or "not measured"); `settable_from`; `in_pinned_build` (false: only in an experiment patch,
named in `source`); `last_checked` (the build and date it was last used, or "never used here"); `reader`; `hazards`;
`source` (where the pinned sources read it); and `companions`, switches that only qualify it. Behaviour and tuning
switches the sources also read are listed by name in `not_diagnostic`, so `check_switches.py` can tell a new
diagnostic switch from them.

The costs are walk medians of the pinned build on 2026-11-19 (1,800-frame walks within 9 m of the Kokiri spawn with
the stutter trace on, the machine at a load average of 6 to 10, one or two runs each), against 18.8-19.1 ms with the
stutter trace alone. They are single measurements under load, good for telling a 3 ms cost from none, not for
ranking switches within a millisecond.

Counts by level: 0: 19, 1: 5, 2: 3, 3a: 19, 3b: 4, 4: 6, 5: 5, 6: 14, hygiene: 4, not-for-timing: 82.

### Level 0: always on

Written in every run without a switch: Lichii's log lines, and what the harness records for every run.

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `nx2:vi2 last 600 presents` | Lichii's own frame counter: mean and max frame time, hitches over 100 ms, GPU fence wait, composite, presents run a frame ahead, vblanks asked against real time. Hazard: counts game presents, menus and loading included; one line covers about 10 s, so it is placed by the time it was written | log: nx2:vi2 last 600 presents: frame N us (max N, N over 100 ms), …; per 600 presents | none (always on) | tools/diag/frames.py vi2 |
| `Runtime pipelines in the last 10 s` | Pipelines built at run time and their GPU-thread ms | log: Runtime pipelines in the last 10 s: N built, …; per 10 s | none (always on) | tools/harness/ab.py (BUILD_RE: settle and the builds count per phase) |
| `Bounded pipeline wait` | Time the GPU thread waited for pipelines still building | log: Bounded pipeline wait: N ms spent in the last 10 s; per 10 s | none (always on) | tools/harness/ab.py (BUILD_RE) |
| `Background prebuild` | The boot's background pipeline prebuild finishing | log: Background prebuild done N s after the boot load began; whole run | none (always on) | tools/harness/ab.py (BUILD_RE) |
| `pipeline build failed` | A graphics pipeline the driver could not build | log: Graphics pipeline build failed: …; per event | none (always on) | tools/harness/ab.py (BUILD_RE) |
| `JIT code cache flush requested` | A JIT flush asked for (debug server jit_clear, EDEN_NX2_JIT_FLUSH_ON_STALL) | log: JIT code cache flush requested (why), generation N; per event | none (always on) | tools/diag/stutter.py flushes |
| `Module main loaded at` | Load address of each guest module (ASLR: differs every boot) | log: Module NAME loaded at 0x… (size 0x…); per event | none (always on) | tools/harness/ab.py (main_base); tools/diag/jit.py log (modules) |
| `Unhandled guest exception` | A guest exception the CPU backend could not handle. Hazard: only the Hypervisor backend writes this text (src/core/arm/hvf/arm_hvf.cpp); a guest crash under dynarmic leaves other lines, so ab.py's crash check does not recognise it | log (critical): Unhandled guest exception: syndrome …, pc …; per event | none (always on) | tools/harness/ab.py (outcome 'guest crashed') |
| `Device fault` | After a Vulkan device loss: what VK_EXT_device_fault reports. Hazard: Lichii exits after a device loss | log (critical): Device fault: …, Device fault address N: …; per event | none (always on) | - |
| `Memory trace` | On the first failed device allocation: process commit, heaps and their budgets. Hazard: the same prefix every 2 s with EDEN_NX2_MEM_TRACE | log: Memory trace: …; per event | none (always on) | - |
| `[mvk-diag] mesh position fixup` | The mesh position fix applied to a mesh shader as it is compiled (off with MVK_ALLINONE_NO_MESH_FLIP) | stderr: [mvk-diag] mesh position fixup added (N mesh shaders so far); per event | none (always on) | tools/harness/ab.py (boot progress in the window title) |
| `stderr.log` | Lichii's stdout and stderr for the run | {rd}/stderr.log; whole run | none (every harness run) | - |
| `hang-sample.txt` | A 3 s macOS sample of Lichii when the boot hangs | {rd}/hang-sample.txt; whole run | none (every harness run) | - |
| `rss_mb / footprint_mb` | Resident memory (ps) and footprint (footprint -p) at the end of the stand | result.json rss_mb, footprint_mb; whole run | none (every harness run) | result.json |
| `loadavg_before / loadavg_after` | The machine's load average around the run | result.json; whole run | none (every harness run) | result.json |
| `fail_status / fail_log` | On an error: debug server status, the last 40 log lines and a screenshot | result.json fail_status, fail_log, fail_shot; {rd}/fail.png; whole run | none (every harness run) | result.json |
| `settle_builds / builds` | Pipeline-build lines while settling and per phase | result.json settle_builds, builds; whole run | none (every harness run) | result.json |
| `picture` | The end picture's corruption score (persist.picture_metrics on run-stand2.png) | result.json picture; run-*.png; whole run | none (every harness run) | tools/harness/persist.py |
| `t_uptime / t_monotonic` | Every harness step on CLOCK_UPTIME_RAW and CLOCK_MONOTONIC_RAW (the clock table) | result.json t_uptime, t_monotonic; whole run | none (every harness run) | tools/diag/rundir.py |

### Level 1: the frame clock

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `frames.bin` | The verify hook's timestamp of every presented frame (CLOCK_UPTIME_RAW ns). Hazard: indices are presents; result.json marks index it | {rd}/frames.bin (little-endian u64 per present); per frame | none measured; every harness run has it | tools/diag/frames.py |
| `frame_times` | Guest-present interval statistics and a VSync histogram over a timed window | debug server reply; whole run | not measured | - |
| `record_frame_times` | Lichii's own frame-time CSV. Hazard: written only on a clean exit: nothing under kill -9, so never in a harness run | a CSV beside the log, written on a clean exit; per frame | not measured | - |
| `status-bar FPS` | The window's fps readout. Hazard: freezes in background captures and shows 60 FPS where the frame clock does not (KNOWN-ISSUES KI-8): never a measurement | the status bar; per second | none (always on) | - |
| `EDEN_NX2_FPS_LOG` | The command-line frontend's FPS, speed and frame time as log lines. Hazard: command-line frontend (eden-cli) only; the app the harness runs never writes it | log: FPS: N speed: N% frametime: N ms; per title update | not measured | - |

### Level 2: the stutter trace

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `EDEN_NX2_STUTTER_TRACE` | Frames over 33 ms with their top cause and each GPU thread's ms, a 10 s summary, boot steps, and with it each core's JIT totals. Hazard: Nx2Stutter only for frames over 33 ms (constexpr StutterMs), so no line for an ordinary frame; frame= counts the trace's presents, not the harness's; jit_cache_mib 6x too high with the shared cache (KI-6); Nx2Boot is the only line that maps log time to the monotonic clock | log: Nx2Stutter, Nx2StutterDetail, Nx2StutterSummary, Nx2Boot … mono_s=, JIT totals core=; per event | not measured (it is the reference of the 2026-11-19 walks: walk median 18.8-19.1 ms, two runs, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-085549 (local run data, not tracked)) | tools/diag/stutter.py |
| `EDEN_NX2_STUTTER_DETAIL_MS` | Frame time over which Nx2StutterDetail adds each thread's largest zones and rare sites (default 50) | log: Nx2StutterDetail; per event | not measured (on in every 2026-11-19 walk at 200) | - |
| `EDEN_NX2_STUTTER_ALL_FRAMES` | An Nx2Stutter line for every frame, to see where an ordinary frame goes. Hazard: about 2.7 MB of log per walk | log: Nx2Stutter for every frame; per frame | walk median 19.1 and 19.9 ms against 18.8-19.1 ms (two runs, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090845 (local run data, not tracked), labels walkcap-allframes-r1/r2) | tools/diag/stutter.py split |

### Level 3a: periodic statistics

Lines that sum a window (a second, 10 s, 600 presents). `stats.py` reads the ones the 2026-11-19 runs have.

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `EDEN_NX2_GUEST_THREAD_STATS` | Per frame, the guest threads with the most core time and where it went; per core, JIT exits, lookups, compiles, counter reads, hints; turns ACQUIRE_STATS on | log: Guest threads over 10.0 s, the per-thread lines, Guest core N over 10.0 s; per 10 s | walk median 19.9 ms with EDEN_NX2_GUEST_THREAD_STATS (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090328 (local run data, not tracked), label walkcap-dkb) | tools/diag/stats.py |
| `EDEN_NX2_GPU_PROFILE` | GPU thread, back thread and Vulkan worker time per second by zone, waits by zone and site, spin-mutex contention; turns ACQUIRE_STATS on. Hazard: its cost skews the frame times it explains: give it its own run | log: <thread> per second: \| zone N ms (N/s) \| …, and more counters; per 10 s | walk median 22.5 ms against 18.8-19.1 ms: about 3 ms (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-gpuprofile) | tools/diag/stats.py |
| `EDEN_NX2_ACQUIRE_STATS` | The GPU front's semaphore acquires and its waits for the back by site | log: Acquires:, GPU thread waits for suspended channels, Front waits for the back in 10 s by site, QMD view; per 10 s | walk median 19.8 ms with BACK_IDLE_TRACE, ACQUIRE_STATS and PRESENT_FENCE_TRACE together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-backidle) | tools/diag/stats.py |
| `EDEN_NX2_BACK_IDLE_TRACE` | The GPU back thread's idle time split by what the front was doing | log: Back idle in 10 s: …; per 10 s | walk median 19.8 ms with BACK_IDLE_TRACE, ACQUIRE_STATS and PRESENT_FENCE_TRACE together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-backidle) | tools/diag/stats.py |
| `EDEN_NX2_PRESENT_FENCE_TRACE` | Presents by the state of their fence at entry and how long until it was reached | log: nx2:vi2 present fences, last 600 presents: …; per 600 presents | walk median 19.8 ms with BACK_IDLE_TRACE, ACQUIRE_STATS and PRESENT_FENCE_TRACE together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-backidle) | tools/diag/stats.py |
| `EDEN_DKB_FRAME_TRACE` | Present, renderer and CPU frame timing and one frame timed on the host GPU (DKB gpu_frame, its 16 costliest passes as DKB gpu_pass). Hazard: its DKB frame and DKB gpu_frame lines are one sample a second, not every frame; on MoltenVK only gpu_pass times are real (gpu_work and gpu_site read 0 or overflowed values) | log: DKB frame, DKB renderer, DKB cpu, DKB draws, DKB gpu_frame, DKB gpu_pass, DKB stale …; per second | walk median 19.9 ms with EDEN_NX2_GUEST_THREAD_STATS (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090328 (local run data, not tracked), label walkcap-dkb) | tools/diag/stats.py |
| `EDEN_NX2_HOSTTIMING_STATS` | CoreTiming's host waits: OS sleep and precise wait time, how late sleeps and events ended. Hazard: also switched live by the debug server's host_timing {"stats": true} | log: HostTiming wait: …; per second | walk median 20.0 ms with HOSTTIMING_STATS and IDLE_STATS together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-timing) | tools/diag/stats.py |
| `EDEN_NX2_IDLE_STATS` | Guest cores' idle periods, how many the poll caught, wake-up latency | log: Guest core N idle over 10.0 s: …; per 10 s | walk median 20.0 ms with HOSTTIMING_STATS and IDLE_STATS together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-timing) | tools/diag/stats.py |
| `EDEN_NX2_BUFFER_TRACE` | Buffers created, joined and collected; SMMU ranges; each buffer of 64 MiB or more | log: Buffer trace: …; per 10 s | walk median 19.4 ms with BUFFER_TRACE, TC_TRACE, DRAW_REUSE_PROBE and TC_LOG together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-caches) | tools/diag/stats.py |
| `EDEN_NX2_TC_LOG` | Texture cache device memory against the collector's thresholds | log: Texture cache: device memory N MiB (expected, critical), N images N MiB; per 600 frames | walk median 19.4 ms with BUFFER_TRACE, TC_TRACE, DRAW_REUSE_PROBE and TC_LOG together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-caches) | tools/diag/stats.py |
| `EDEN_NX2_DRAW_REUSE_PROBE` | Draws per frame by reuse class and their PrepareDraw cost | log: Draw reuse per frame over N frames: …; per 10 s | walk median 19.4 ms with BUFFER_TRACE, TC_TRACE, DRAW_REUSE_PROBE and TC_LOG together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-caches) | tools/diag/stats.py |
| `EDEN_NX2_DOWNLOAD_TRACE` | What the buffer cache copies back to guest memory at fences, and guest reads of GPU-written ranges. Hazard: only the first 2,000 guest reads are logged (in that run the cap was reached during the walk); the 10 s lines appear only when something was copied back | log: Download trace, … in 10 s; Download trace: CPU read of GPU-written […) …; per 10 s | walk median 19.0 ms (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-download) | tools/diag/stats.py |
| `EDEN_NX2_MEM_TRACE` | What the texture and buffer caches hold next to what the process and driver report; and the title's first memory layout and size queries. Hazard: the SVC part logs the first 200 queries per event | log: Memory trace: …; per 2 s | not measured | - |
| `EDEN_NX2_LIST_MACRO_TRACE` | GPU-written command list entries the front waits for and the native macros they feed | log: List macro trace in 10.0 s, List macro reader; list-macro-*.txt in EDEN_NX2_DEBUG_DIR; per 10 s | not measured | - |
| `EDEN_NX2_FS_READ_TRACE` | Guest RomFS and file reads: count, MiB, latency. Hazard: lines only while the guest reads | log: Guest storage reads, Guest file reads; per second | not measured (one run on 2026-11-19 completed with it, run ab-20261119-093044 (local run data, not tracked), label fu-fsread) | tools/diag/stats.py |
| `EDEN_NX2_HVF_STATS` | Hypervisor backend exits: SVCs, trapped system registers, faults. Hazard: Hypervisor backend only (not the pinned build's CPU backend) | log: Hypervisor exits per second; per 10 s | not measured | - |
| `EDEN_NX2_IPC_SUMMARY` | How often each service command ran and with which result | log: IPC summary lines; per 5 s | not measured | - |
| `EDEN_NX2_MME_MEMO_STATS` | The macro memo's counters | log: memo counters; every 2^24 macro calls | not measured | - |
| `EDEN_NX2_CMDPAGE_DIAG` | Command list pages that GPU work writes: whether it writes the lists' own words, and what the front's slow path costs | log: counts; per 2 s | not measured | - |

### Level 3b: per event

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `EDEN_NX2_TC_TRACE` | Every image the texture cache creates, uploads, deletes or makes over stale pages. Hazard: about 30,000 lines a walk (9.8 MB of log with the other cache switches) | log: TCTRACE create / delete / upload / stale-skip; per event | walk median 19.4 ms with BUFFER_TRACE, TC_TRACE, DRAW_REUSE_PROBE and TC_LOG together (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-091354 (local run data, not tracked), label walkcap-caches) | tools/diag/stats.py |
| `EDEN_NX2_PIPELINE_BUILD_TRACE` | A flushed BEGIN / END line per driver pipeline build with the stage hashes and wall time. Hazard: times include waiting on other builds | the file it names; per event | not measured | - |
| `EDEN_NX2_PIPELINE_DIFF` | For a new pipeline whose shaders an earlier one uses, which fixed state differs | log; per event | not measured | - |
| `EDEN_NX2_READBLOCK_TRACE` | Every read of unmapped device memory with its caller (else the first 16) | log: Unmapped Device ReadBlock …; per event | not measured | - |
| `EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS` | With EDEN_NX2_GUEST_THREAD_STATS, makes each report window one present-to-present interval and logs only windows at least this many ms long: what every guest thread did in each slow frame. Hazard: only in patches/experiments/lichii-thread-stats-slow-frames-2026-11-19.patch: needs a test build in a private data root; the window is between guest presents, which is not the hook's present-to-present interval, so match a block to its frame by the Nx2Stutter line that follows it; figures are per present in the window | log: Guest threads over 0.0NNN s, the per-thread lines, Guest core N lines, one block per slow window; per event | walk median 19.8 ms with EDEN_NX2_GUEST_THREAD_STATS_SLOW_MS=28 (one run, 1,800-frame leashed walk at the Kokiri spawn, load average 9; run ab-20261119-094316 (local run data, not tracked), label probe-threads-r1) | - |

### Level 4: the GPU side

`MVK_FRAMEPROF` records P (present), T (clock pair), C (command buffer: frame, GPU start and end, encoders,
unsampled, kernel start and end, first encoder's host time), S (its encoders summed by signature: count, span,
vertex, fragment, work, groups, indirect) and E (every encoder, only for every 150th frame). `P60_SYNC_TRACE` tags:
`frontwait` (the GPU front waited for its back; site from `DrainSite` in `video_core/gpu_split.h`), `gpuwait`
(`Scheduler::Wait` for the host GPU), `hostwait` (a read download waited, by a reader thread or the GPU side),
`flush` and `finish` (a submit and its call site), `copy`, `copy-batched`, `copy-reordered` (buffer copies by site,
with bytes).

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `MVK_FRAMEPROF` | MoltenVK's frame profiler: GPU start and end of every command buffer, its encoders summed by signature, every 150th frame encoder by encoder. Hazard: E records only for frames where frame % 150 == 0 (dump in MVKFrameProf.mm); about 46-48 MB per walk; host clock is mach_absolute_time in us | {rd}/frameprof.txt (records P, T, C, S, E); per frame | walk median 19.8 ms in both runs with MVK_FRAMEPROF and P60_SYNC_TRACE together (1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090328 (local run data, not tracked), labels walkcap-gpu-r1/r2); an earlier build measured its own overhead under 0.2 ms (research/allinone-frame-breakdown) | tools/diag/gpu.py |
| `MVK_FRAMEPROF_DUMP_MS` | With MVK_FRAMEPROF, also writes the per-encoder E records of every command buffer whose GPU interval is at least this many ms, so a stalled command buffer shows which pass waited. Hazard: only in patches/experiments/moltenvk-frameprof-dump-long-buffers-2026-11-19.patch: needs a test build in a private data root | {rd}/frameprof.txt (E records after the long command buffer's S records); per event | walk median 19.6 ms with MVK_FRAMEPROF, P60_SYNC_TRACE and MVK_FRAMEPROF_DUMP_MS=6 (one run, 1,800-frame leashed walk at the Kokiri spawn, load average 9; run ab-20261119-094316 (local run data, not tracked), label probe-encoders-r1) | tools/diag/gpu.py gapctx |
| `P60_SYNC_TRACE` | A line per synchronisation event: frontwait, gpuwait, hostwait, flush, finish, copy, copy-batched, copy-reordered. Hazard: 200-250 MB per walk; CLOCK_UPTIME_RAW ns | {rd}/sync.txt (<ns> <tag> <where> <a> <b>); per event | walk median 19.8 ms in both runs with MVK_FRAMEPROF and P60_SYNC_TRACE together (1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090328 (local run data, not tracked), labels walkcap-gpu-r1/r2) | tools/diag/gpu.py |
| `MVK_CONFIG_PERFORMANCE_TRACKING` (with `MVK_CONFIG_PERFORMANCE_LOGGING_FRAME_COUNT`, `MVK_CONFIG_ACTIVITY_PERFORMANCE_LOGGING_STYLE`, `MVK_CONFIG_PERFORMANCE_LOGGING_INLINE`) | MoltenVK's own activity performance counters | stderr (MoltenVK log); per N frames | not measured | - |
| `MVK_CONFIG_LOG_LEVEL` | MoltenVK's log level (tools/verify runs with 2, errors) | stderr; per event | not measured | - |
| `MVK_CONFIG_TRACE_VULKAN_CALLS` | A line per Vulkan call MoltenVK receives. Hazard: per call: tens of thousands a frame | stderr; per event | not measured | - |
| `MVK_CONFIG_DEBUG` (with `MVK_DEBUG`) | MoltenVK debug mode (shader conversion logging and checks) | stderr; per event | not measured | - |

### Level 5: the JIT

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `DYNARMIC_JIT_TRACE` | Every code cache operation: lookups that missed a Jit's table, compiles with their guest instructions, fastmem faults, invalidations, clears. Hazard: its clock starts at the first record; replays offline with DYNARMIC_JIT_REPLAY in the PR #2101 test tree | {rd}/jit-trace.bin (32-byte records); per event | walk median 19.2 ms with ALL_FRAMES (one run, 1,800-frame leashed walks at the Kokiri spawn, load average 6-10; run ab-20261119-090845 (local run data, not tracked), label walkcap-jitrec); the file was 445 MB for one boot, save load and walk | tools/diag/jit.py trace |
| `DYNARMIC_BLOCK_MAP` | Host entry, size and guest PC range of every compiled arm64 block | the file it names (text, line buffered); per event | not measured | - |
| `EDEN_NX2_JIT_SYMBOLS` | Names of JIT blocks for the Windows sampler. Hazard: takes a process-wide lock per compiled block; only the Windows sampler reads the names | none on macOS; per event | not measured | - |
| `EDEN_NX2_JIT_LOG` | One record per compiled block: core, guest PC, time in each compile phase. Hazard: only in patches/experiments/dynarmic-jit-log-2026-11-17.patch: needs a test build in a private data root. Not in the pinned build: `patches/experiments/dynarmic-jit-log-2026-11-17.patch` | {rd}/jit.bin (40-byte records); per event | not measured | tools/diag/jit.py log |
| `DYNARMIC_ARM64_REGION_SIZE` | Test setting: smaller code regions, so veneers happen in a small cache. Hazard: changes code generation: never for a measurement | none; whole run | not measured | - |

### Level 6: OS and heavy tools

These change what they measure (a pause, a validation layer, a capture): use them outside measured phases, or in
runs whose frame times are not used.

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `sample` | MacOS's stack sampler on a running Lichii. Hazard: never during a measured phase | a text report; whole run | pauses the process while it samples (TRACKER.md, measurement rules) | build/src/lichii/tools/nx2/macos_sample.py (per-thread summary) |
| `EDEN_NX2_SAMPLE` (with `EDEN_NX2_SAMPLE_OUT`, `EDEN_NX2_SAMPLE_START`, `EDEN_NX2_SAMPLE_SECONDS`) | Lichii's built-in thread sampler. Hazard: Windows only (src/common/nx2_sampler.cpp) | EDEN_NX2_SAMPLE_OUT; whole run | not measured | - |
| `sample (debug call)` | The built-in sampler through the debug server. Hazard: Windows only: returns 'the sampler is Windows only' | debug server reply; whole run | not measured | - |
| `footprint` | MacOS's memory footprint of a process | text; whole run | none measured; the harness runs it once after the stand | tools/harness/ab.py (footprint_mb) |
| `metalperftrace` | Apple's always-on Metal performance record: per second, for each program that draws through a Metal layer, frames, time on the GPU, CPU begin-to-present time, drawable wait; resource use per process. Hazard: per second and per program, with nothing per pass: it cannot show who had the GPU inside one frame; its earlier reader (mpt_report.py) is lost; never attach listen | `metalperftrace collect --last 10m DIR` writes an .atrc file for any past window; `metalperftrace overview [--json --json-include-timeline] FILE` prints it; per second | collect is passive (the record is always on); listen hung two runs (TRACKER.md) | - |
| `shotwatch` | Asks the frame hook for a window capture ten times a second beside a running harness batch, scores each one and keeps only the captures with a wrong picture (clipped white), with a CSV line for every capture; can take a bug bundle and a GPU trace when a boot comes up bad. Hazard: captures before presented frame 1,500 are never kept (the boot logos are white); a clean Kokiri Forest scene scores 0.0 % white and the canopy-shard picture 2.6-2.8 %; the bright-saturated score flags a yellow lantern near the camera, so it is off unless asked for | OUT_DIR/shots.csv, bad-*.png, ref-*.png; per event | about 40-50 ms per capture on the hook's control thread; walk median 19.5 ms and p95 23.2 ms during a 20 s watch against 19.6 and 24.2 ms before it in the same walk (one sample; run ab-20261119-093044 (local run data, not tracked), label fu-fsread) | - |
| `Instruments / xctrace` | Apple's profiler. Hazard: never tried here | a .trace bundle; whole run | not measured | - |
| `MTL_DEBUG_LAYER` (with `MTL_DEBUG_LAYER_ERROR_MODE`, `MTL_DEBUG_LAYER_WARNING_MODE`) | Metal API validation | stderr / unified log; per event | frames 4-6x slower, about 250 ms, with shader validation (TRACKER.md) | - |
| `MTL_SHADER_VALIDATION` (with `MTL_SHADER_VALIDATION_REPORT_TO_STDERR`, `MTL_SHADER_VALIDATION_RESOURCE_USAGE`) | Metal GPU validation: every shader instrumented. Hazard: crashes in MTLToolsResidencySet unless MTL_SHADER_VALIDATION_RESOURCE_USAGE=0 | stderr / unified log; per event | frames 4-6x slower, about 250 ms, with the API layer (TRACKER.md) | - |
| `MTL_LOG_COMPILE_STATS` | Metal's per-pipeline compile statistics (cache hit or compiled). Hazard: the payload is <private> unless read in-process with oslogtap.dylib (DYLD_INSERT_LIBRARIES) | unified log (<private>); stderr with oslogtap.dylib; per event | not measured | wip/shader-prebuild/scripts/metal-probes/oslogtap.c |
| `MVK_CONFIG_AUTO_GPU_CAPTURE_SCOPE` (with `MVK_CONFIG_AUTO_GPU_CAPTURE_OUTPUT_FILE`, `MVK_CONFIG_DEFAULT_GPU_CAPTURE_SCOPE_QUEUE_FAMILY_INDEX`, `MVK_CONFIG_DEFAULT_GPU_CAPTURE_SCOPE_QUEUE_INDEX`) | MoltenVK's automatic Metal GPU capture (device or frame scope). Hazard: a capture stalls the GPU and is game data | a .gputrace file (MVK_CONFIG_AUTO_GPU_CAPTURE_OUTPUT_FILE); whole run | not measured | - |
| `EDEN_NX2_GPU_TRACE` (with `EDEN_NX2_GPU_TRACE_PRESENTS`) | A GPU trace (.lxtrace: snapshot, submits, CPU writes, maps, presents) starting when <dir>/record.now appears. Hazard: 2.3 GB for 120 presents; holds game data | <dir>/trace-*.lxtrace; whole run | a recording GPU trace costs 54 ms a frame (TRACKER.md, measurement rules) | tools/speckcheck, tools/statecheck (replay with eden-cli --replay) |
| `trace_record` (with `trace_stop`, `trace_status`) | The same GPU trace started through the debug server (in a spec: server_calls) | an .lxtrace in the debug server's dump folder; whole run | 54 ms a frame while recording (TRACKER.md) | tools/speckcheck, tools/statecheck |
| `capture_bundle` | The Report a Bug bundle: logs, settings, screenshot, frame times, a frame capture with shaders. Hazard: holds game data | a zip; whole run | 24 MB zip in 6.6 s (research/emulator-options) | build/src/lichii/tools/nx2/bundle_index.py |
| `use_gdbstub` | Lichii's GDB stub; the harness's jsdbg attaches lldb through it. Hazard: needs jsdbg.py from the glitch-research repository | lldb session (jsdbg.log); whole run | about 4 ms a frame walking with a debugger attached (TRACKER.md) | - |

### Measurement hygiene

| Switch | What | Output, granularity | Cost | Reader |
| --- | --- | --- | --- | --- |
| `MVK_P60_NO_APPNAP` | Keeps macOS from napping the process while its window is hidden (which moves it to the efficiency cores and makes frame times bimodal). Hazard: set by ab.py and by config/launch-env.txt; a run without it can land on the efficiency cores | none; whole run | none measured; every harness run sets it | - |
| `log_filter` | The log filter (default *:Info); also live through the debug server. Hazard: a Debug filter on busy classes floods the log | the log; whole run | not measured | - |
| `flush_line` | Flush the log after every line instead of 4 KiB buffers. Hazard: without it a kill -9 loses at most the last second of lines below Error | the log; whole run | not measured | - |
| `extended_logging` | Raises the log's size limit from 100 MiB to 1 GiB. Hazard: at the limit the log stops being written (src/common/logging.cpp:312) | the log; whole run | not measured | - |

### Not for timing

Verification and check switches (they do the work twice), dumps and captures, protocol traces (a line per call or
method), bisect hooks, Mesa-only variables and experiment-patch switches. They answer correctness questions; their
frame times mean nothing.

| Switch | What it does | Owner |
| --- | --- | --- |
| `EDEN_NX2_ACQUIRE_VERIFY` | =1: the acquire statistics also verify the acquires. | lichii |
| `EDEN_NX2_BACKX_VERIFY` | Each lock or gather the back skips also runs the locked check. | lichii |
| `EDEN_NX2_DELTA_DESCRIPTORS_VERIFY` | Delta draws resolve their image descriptors in full too and compare. | lichii |
| `EDEN_NX2_DMA_READ_VERIFY` | A macro DMA read made without draining the split drains anyway and is compared. | lichii |
| `EDEN_NX2_FAST_DRAW_VERIFY` | Checks the fast draw path (purpose not confirmed from the source). | lichii |
| `EDEN_NX2_LIST_MACRO_VERIFY` | The list macro trace plus a forwarding check of every call. | lichii |
| `EDEN_NX2_PERF_VERIFY` | Checks the 3D engine's performance shortcuts (purpose not confirmed from the source). | lichii |
| `EDEN_NX2_REG_BLOCK_VERIFY` | Register blocks also run write by write and are compared. | lichii |
| `EDEN_NX2_SPLIT_VERIFY` | Every 4096 front macro calls, compare the front's registers with the back's. | lichii |
| `EDEN_NX2_TEXTURE_MEMO_VERIFY` | Draws resolved from the texture memo are also resolved in full. | lichii |
| `EDEN_NX2_UBO_KEEP_VERIFY` | Binds what a uniform keep would skip and logs where guest memory changed. | lichii |
| `EDEN_NX2_DRAIN_CHECK` | The back compares the front's QMD view with its own. | lichii |
| `EDEN_NX2_LIST_INDIRECT_CHECK` | The front also reads every list the host GPU takes and compares. | lichii |
| `EDEN_NX2_LIVE_READ_CHECK` | Counts entries parsed from memory that differ from their submit-time copy. | lichii |
| `EDEN_NX2_PB_CHECK` | Pushbuffer entries that change between submit and parse. | lichii |
| `EDEN_NX2_READ_CHECK` | =<n>: compares 1 in n read downloads with a synchronous flush. | lichii |
| `EDEN_NX2_SPLIT_CHECK` | Reports scheduler use from the wrong thread. | lichii |
| `EDEN_NX2_DUMP` | At a present, save GPU ranges' bytes to the frame capture folder. | lichii |
| `EDEN_NX2_FRAME_CAPTURE` (with `EDEN_NX2_FRAME_CAPTURE_EVERY`) | Every 120th present saved as a .tga. | lichii |
| `EDEN_NX2_FRAME_DUMP` (with `EDEN_NX2_FRAME_DUMP_AT`, `EDEN_NX2_FRAME_DUMP_SAMPLED`) | One frame's passes, targets and present source (Lichii tools/nx2/frame_dump_index.py). | lichii |
| `EDEN_NX2_MESH_EMULATION_DUMP` | The mesh emulation's vertex shader for spirv-val. | lichii |
| `EDEN_NX2_MESH_EMULATION_PROBE` | Every 60 frames, read one emulated mesh draw's output back. | lichii |
| `EDEN_NX2_MME_DUMP` | Compute macro code and every compute macro call. | lichii |
| `EDEN_NX2_MME_RECORD` (with `EDEN_NX2_MME_RECORD_SKIP`) | The first 200,000 macro calls and the macro code, for offline checks. | lichii |
| `EDEN_NX2_PB_DUMP` | The whole command list for offline replay. | lichii |
| `EDEN_NX2_SHADER_DUMP` | Every captured native program, for offline lowering tests. | lichii |
| `EDEN_NX2_TEXTURE_DUMP` | The first 4 MiB of the last traced texture. | lichii |
| `EDEN_NX2_VDEC_DUMP` | The luma of every 120th decoded video frame. | lichii |
| `EDEN_NATIVE_DRAW_CAPTURE` | The first 16 native draws' state. | lichii |
| `EDEN_NATIVE_FRAME_CAPTURE` | Native graphics macro code to native-graphics-mme-*.bin. | lichii |
| `capture_frame` | The next frame's passes, shaders, targets, sampled textures and buffers (a spec's capture). | lichii |
| `EDEN_NX2_IPC_TRACE` | Every dispatched service command and its result. | lichii |
| `EDEN_NX2_SVC_TRACE` | Every SVC with its arguments and results (or presents first:last). | lichii |
| `EDEN_NX2_METHOD_TRACE` | Every GPU engine method call. | lichii |
| `EDEN_NX2_PULLER_TRACE` | Every GPU puller method. | lichii |
| `EDEN_NX2_RENDER_TRACE` | Per-draw state, rejected stages, zero-format descriptors. | lichii |
| `EDEN_NX2_QUERY_TRACE` | Every counter report. | lichii |
| `EDEN_NX2_MME_LOG` | Every macro call. | lichii |
| `EDEN_NX2_CB24_TRACE` | Draws whose vertex shader reads bank 24: the inline upload target. | lichii |
| `EDEN_NX2_RT_TRACE` | The first draw to every distinct colour target. | lichii |
| `EDEN_NX2_QMD_TRACE` | The QMD scheduler's loads, dependency counts and launches. | lichii |
| `EDEN_NX2_TABLE_POINTER_TRACE` | Changes of table pointer slots and whether the two copies can differ. | lichii |
| `EDEN_NX2_PENDING_WRITE_TRACE` | Reads that hit collected guest writes not yet applied. | lichii |
| `EDEN_NX2_QUERY_DMA_TRACE` | Macro DMA reads of reports whose host results are not in guest memory yet. | lichii |
| `EDEN_NX2_UPSCALER_TRACE` (with `EDEN_NX2_UPSCALER_TRACE_FRAME`, `EDEN_NX2_UPSCALER_TRACE_FRAMES`) | The upscaler's dispatches over a few frames. | lichii |
| `EDEN_NX2_VDEC_TRACE` | Video decoder submit, decode and composite. | lichii |
| `EDEN_NX2_WINDOW_TRACE` (with `EDEN_NX2_WINDOW_TRACE_SKIP`) | Clears and draws into screen-sized colour targets. | lichii |
| `EDEN_NX2_3D_HISTORY` | A history of 3D engine writes (purpose not confirmed from the source). | lichii |
| `EDEN_NX2_3D_METHODS` | The first write to each 3D register. | lichii |
| `EDEN_NX2_SEM_WATCH` (with `EDEN_NX2_SEM_WATCH_EMITS`) | Every method whose argument is the low word of the watched semaphore address. | lichii |
| `EDEN_NX2_TRACE_DST` | Copies writing within 32 MiB above an address. | lichii |
| `EDEN_NX2_TRACE_PS` | The draw trace limited to one pixel shader. | lichii |
| `EDEN_NX2_TRACE_VS` | The next draws using a vertex shader. | lichii |
| `EDEN_NX2_HANDLE_TABLE_NOTES` | Notes on shader handle tables (purpose not confirmed from the source). | lichii |
| `EDEN_NX2_DLSS_CONTRACT_TRACE` (with `EDEN_NX2_DLSS_CONTRACT_SKIP`) | Inputs and outputs of replaced upscaler networks. | lichii |
| `EDEN_NX2_DLSS_LOG` | Streamline's log level (DLSS on Windows). | lichii |
| `EDEN_NATIVE_DRAW_DIAGNOSTICS` | Native query and draw events, bounded. | lichii |
| `EDEN_DKB_INDIRECT_READBACK` | With the frame trace, read indirect draw arguments back. | lichii |
| `EDEN_STARFOX_WINDOW_TRACE` | Star Fox window and texture registrations. | lichii |
| `EDEN_NX2_AUDIO_LEVEL` | The audio output peak about every two seconds. | lichii |
| `EDEN_NX2_FAULT_MAP` | After a device loss, what each fault address belonged to. | lichii |
| `EDEN_NX2_KEY_RECORD` | The command-line frontend appends each key press and release to a file. | lichii |
| `EDEN_NX2_REJECT` | Treat programs at these addresses as rejected (bisect a lowered program). | lichii |
| `EDEN_NX2_REJECT_HASH` | The same by native program key or shader hash. | lichii |
| `EDEN_NX2_SKIP_VS` | Drop draws that use these vertex shaders. | lichii |
| `EDEN_NX2_NO_MESH` (with `EDEN_NX2_NO_MESH_FILE`) | Skip task and mesh draws (A/B), or while a file exists. | lichii |
| `EDEN_NX2_FORCE_LOD0` | Sample only the top mip level. | lichii |
| `EDEN_NATIVE_SHADER_OVERRIDE_DIR` | Load replacement native shaders from a folder. | lichii |
| `MVK_DIAG_OVERRIDE_DIR` | Replace Metal shader source: <name>.orig.metal with <name>.repl.metal. | ours-moltenvk-patch |
| `MVK_DIAG_INVARIANT` | Mark vertex positions invariant in every shader. | ours-moltenvk-patch |
| `MVK_DIAG_NO_OPTNONE` | Drop [[clang::optnone]] from shaders. | ours-moltenvk-patch |
| `MVK_ALLINONE_NO_MESH_FLIP` | Turn the mesh position fix off. | ours-moltenvk-patch |
| `MVK_CONFIG_SHADER_DUMP_DIR` | Write every converted Metal shader to a folder (tools/perf/tg_audit.py reads it). | moltenvk |
| `MVK_CONFIG_SHADER_LOG_ESTIMATED_GLSL` | With MVK_CONFIG_DEBUG, log an estimated GLSL of every converted shader. | moltenvk |
| `MESA_SHADER_CACHE_DISABLE` (with `MESA_GLSL_CACHE_DISABLE`) | Mesa only: the shader cache is off (Lichii checks it). | lichii |
| `RADV_DEBUG` | Mesa RADV only: =hang writes a hang report. | lichii |
| `SSLKEYLOGFILE` | Writes the TLS session keys to a file: never set it. | lichii |
| `EDEN_NX2_DIAG_DEPTH_EQUAL` | Replaces the depth test of every pipeline. Only in `patches/experiments/lichii-render-diagnostics.patch`. | ours-lichii-patch |
| `EDEN_NX2_DIAG_DRAW_BUFFERS` | The buffers bound to a program's first draws. Only in `patches/experiments/lichii-render-diagnostics.patch`. | ours-lichii-patch |
| `EDEN_NX2_DIAG_STAGE_INFO` | Which stages of every pipeline have shader info and buffers. Only in `patches/experiments/lichii-render-diagnostics.patch`. | ours-lichii-patch |
| `EDEN_NX2_DIAG_WATCH_UPLOADS` | Every upload of guest memory over the watched device ranges. Only in `patches/experiments/lichii-render-diagnostics.patch`. | ours-lichii-patch |
| `EDEN_NX2_HVF_SITES` | With EDEN_NX2_HVF_STATS, the guest PCs with the most interpreted accesses. Only in `patches/experiments/hvf-experiments-2026-11-17.patch`. | ours-lichii-patch |

## Upstream descriptions

- `build/src/lichii/AGENTS.md`, "Debugging tools": Lichii's table of switches, by symptom, with what each logs.
- `build/src/lichii/docs/nx2/debug-mcp.md` (the debug server's calls), `gpu-trace.md` (GPU trace recording and
  replay), `bug-bundle.md` (the bug-report bundle).
- `build/src/moltenvk/Docs/MoltenVK_Configuration_Parameters.md`: every `MVK_CONFIG_*` parameter.
- [`research/metal-validation`](../../research/metal-validation/README.md): Apple's Metal validation variables as
  used here.
