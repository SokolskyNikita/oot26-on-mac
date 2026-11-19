# Tools

| Folder | What it does |
| --- | --- |
| [harness/](harness/README.md) | Runs the game unattended through Lichii's debug server and compares settings, builds and patches: boots, loads a save by name, walks, stands, records frame times and pictures |
| [pad/](pad/README.md) | A virtual DSU controller and its client; only `verify.py run` uses it, and starts it itself |
| [verify/](verify/README.md) | The emulator lock every tool takes before starting Lichii, the frame hook that timestamps each presented frame, and an older single-run checker |
| [statecheck/](statecheck/README.md) | Replays a recorded GPU trace and checks, draw by draw, that Metal holds the raster state Vulkan asked for |
| [speckcheck/](speckcheck/README.md) | Screenshot bursts scored for white specks, and GPU trace replay with shader overrides |
| [jit-cache/](jit-cache/README.md) | Measurement scripts and run specs for the shared JIT code cache |
| [perf/](perf/README.md) | Frame-profile comparison scripts from the frame-time work |

The harness drives the game through Lichii's debug server and needs no controller server. Setting it up on a new
machine (the app, the frame hook, the master config, the save, a smoke test) is in
[harness/README.md](harness/README.md#setting-up-on-a-new-machine). Your dump of the game is found through
`OOT26_DUMP`, or in `dump/` in this repository or beside it.
