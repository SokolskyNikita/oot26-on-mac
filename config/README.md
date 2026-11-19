# Configuration of the pinned build

What sits outside the source: the switches the app ships with, how it is launched, and the emulator settings every
number in this repository was measured with.

## Files here

| File | What `build.sh app` does with it |
| --- | --- |
| `nx2_switches.append.txt` | Appended to Lichii's own `dist/nx2_switches.txt` to make the app's `Contents/MacOS/nx2_switches.txt`. One line: `EDEN_NX2_SHARED_JIT_CACHE=512`. |
| `settings.txt`, `apply-settings.py` | Not used by the build. The emulator settings below as `KEY=VALUE`, and a script that checks them against `~/.config/lichii/qt-config.ini` (`--check`) or applies them. |
| `launch-env.txt` | `NAME=VALUE` lines written into the app's `Info.plist` (`LSEnvironment`), which apply to launches through Finder, the Dock or `open`: the bilinear stand-in for the game's upscaling network and the App Nap opt-out. The harness starts the binary directly, so its numbers are with the game's own network unless a run sets the switches itself. |

Active switches in the assembled app: `EDEN_NX2_SPLIT=2` and `EDEN_NX2_FENCE_BATCH=1` (Lichii's own defaults) and
`EDEN_NX2_SHARED_JIT_CACHE=512`.

## Where Lichii keeps its state

| What | Where |
| --- | --- |
| Settings | `~/.config/lichii/qt-config.ini`, and per game `~/.config/lichii/custom/0400486024DEC000.ini` |
| Data (saves, mods, logs) | `~/.local/share/lichii` |
| Shader caches | `~/.cache/lichii/shader/0400486024dec000/` and the Metal cache in `$(getconf DARWIN_USER_CACHE_DIR)/io.github.zortos293.lichii/` |

Lichii rewrites `qt-config.ini` when it quits, so quit it before editing the file. Resolution can only be changed
with the game closed. No keys or firmware are installed in this setup.

## Settings

| Setting | Value | Why |
| --- | --- | --- |
| Resolution | 1x (`resolution_setup=3`) | |
| Mode | handheld (`use_docked_mode=0`) | docked is about 5 ms a frame slower |
| Post-processing | off | the game is GPU-bound |
| `gpu_accuracy` | 0 (Low) | same |
| `use_asynchronous_shaders` | true | |
| `scaling_filter` | 1 (Bilinear) | |
| `anti_aliasing` | 0 | |
| `oot_anti_aliasing` | 1 (No sharpening) | |
| `cpu_accuracy` | 0 (Auto) | 1 (Accurate) before debugger work: fewer load crashes under lldb, no frame cost |
| `native_async_draws` | 1 (Bounded) | Lichii's recommended table |
| `async_presentation` | true | same |
| `nvdec_emulation` | 2 (Gpu) | same |
| `build_all_cached_shaders` | true | same |
| Built-in "Max Resolution", "FPS Unlock", "Dynamic FPS" patches | off | Lichii applies them silently. FPS Unlock rewrites 35 places in the game's code and changes how time steps. |
| `use_gdbstub` | `true` only for debugging | with it on, Lichii waits for a debugger at boot |

About 60 settings and switches were measured one by one; the defaults win almost everywhere. The table is in
[../research/emulator-options/README.md](../research/emulator-options/README.md).

## The shader cache and MoltenVK

Every Lichii app on a machine shares one Metal cache and one Vulkan pipeline file, and the Metal cache is tied to
the MoltenVK binary. A different `libMoltenVK.dylib`, even one rebuilt from the same source, makes the next boot
compile every shader again: about 100 s with this build, 455–483 s without MoltenVK #2901. Switching back costs the
same again. So:

- After `build.sh install`, the first boot is slow once.
- When comparing two apps where MoltenVK is not what changed, give both the same library file.
- A slow boot is not a hang. Check for a library mismatch (`shasum`) before touching the caches.
