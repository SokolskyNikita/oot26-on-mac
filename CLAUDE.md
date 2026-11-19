# Working in this repository

A pinned, rebuildable build of the Lichii emulator for the 2026 Switch 2 remake of Ocarina of Time on an Apple
silicon Mac, with its patches, measurement tools and research. Start with [README.md](README.md). What is in the
build and what was tried: [TRACKER.md](TRACKER.md). What is wrong with it: [KNOWN-ISSUES.md](KNOWN-ISSUES.md).

## Running the emulator: the rules

1. **Use the harness, not a hand-rolled launch.** `tools/harness/queue.sh SPEC.json` boots the game, loads a save by
   name, drives it, measures, scores the picture and restores the config. Read
   [tools/harness/README.md](tools/harness/README.md) before the first run. Write a new spec rather than a new
   launch script.
2. **One emulator at a time: the lock.** `~/.local/share/lichii/verify.lock` is held by whoever runs Lichii.
   `queue.sh` takes it. Anything else that starts Lichii runs as `tools/verify/verify.py with-lock -- COMMAND`. Check
   with `tools/verify/verify.py lock-status` before starting; if it is held, wait. Never kill a Lichii you did not
   start, and never remove the lock by hand unless `lock-status` shows a dead owner.
3. **Input goes through Lichii's debug server.** The harness sends buttons and sticks with the debug server's
   `input` and `input_sequence` calls (`tools/harness/dbg.py`). No controller server is needed. The DSU pad in
   `tools/pad/` exists only for `tools/verify/verify.py run` (which starts it itself) and for older live drivers in
   the glitch-research repository; do not start it for harness runs and do not build new tools on it.
4. **Game state comes from memory, never from a screenshot.** Screenshots are for checking the picture afterwards,
   and they must be looked at: picture corruption does not show in the logs.
5. **Only the pinned app on the real folders.** `build/app/lichii.app` (the same as `/Applications/lichii.app`) is
   the only app that may run against `~/.config/lichii`, `~/.local/share/lichii` and `~/.cache/lichii`. A different
   Lichii build, or a MoltenVK library with a different pipeline cache id, makes the next boot translate every shader
   again (about 330 s), and so does coming back. Any other build runs in a private data root: `"home"` in the spec,
   made with `python3 tools/harness/ab.py --make-home DIR`, and with its own bundle id.
6. **Never execute a Lichii binary directly**, not even with `--help` or `--version`: it opens the GUI, rotates the
   log and rewrites the config. `eden-cli` is only run by `tools/statecheck/record.sh` and
   `tools/speckcheck/replay.sh`, which give it a private data folder.
7. **Stop Lichii with `kill -9`**, as the harness does. The Quit menu rewrites the config.
8. **Long commands run in the background** with a shell `timeout`; a build or a harness batch is never run in the
   foreground with a raised tool timeout.

## Changing the pinned build

A change is a commit on branch `gold` in `build/src/lichii` or `build/src/moltenvk` (author date equal to committer
date, so `build.sh` reproduces the commit id), a re-export of the patch series, new ids in `versions.lock`, a row in
`TRACKER.md`, and a comparison against the installed build in the harness with the pictures looked at. A MoltenVK
change that touches shader translation also needs a new `MOLTENVK_CACHE_ID`. `./build.sh install` is the only way the
app in `/Applications` changes.

## Where things go

- A finished result: a write-up under `research/<topic>/`, stating what is true now, not how it was reached.
- Unfinished work: `wip/<topic>/`, large local data in its git-ignored `local/`.
- A fault of the pinned build: a row in `KNOWN-ISSUES.md`. An experiment or an idea: `TRACKER.md`.
- Run data stays in `tools/harness/runs/` (not tracked); cite it as "run ab-… (local run data, not tracked)".
