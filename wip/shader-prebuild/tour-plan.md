# Fly-through tour: plan

A scripted flight through every warp map, so the training caches record what no saved play has drawn. Planned on
2026-11-17 from offline counts and the existing tools; nothing was launched. Each statement is marked **verified**
(with how) or **assumed**. Context: [README.md](README.md), [precompiled-file.md](precompiled-file.md).

## Verdict

**The tour is feasible with today's tools, and the warp hang does not block it.** But the rebuild rule as
proposed ("drop unseen pairs in shader files the tour exercised") would shrink the file very little if applied
safely. Applied everywhere, it would drop pipelines the game still uses:

- 97% of the pairs the rule would drop (18,806 of 19,485, using today's three caches as a stand-in for a tour)
  sit in 8 shared files: `Shader/Model.Product.110…bfsha` alone has 12,458 pairs, and the agl and Terrain archives
  hold most of the rest. Every map's models draw from those files, so seeing some of a file's pairs says nothing
  about the others. Excluding them, the rule drops about 700 pairs.
- What actually shrinks the file is keeping **one prediction per pair** wherever the tour did not reach. That takes
  it from 311,091 records to about 45,000–65,000. The cost: for content the tour misses, fragment-side coverage falls
  from 91% to about 37%. Those are the README's held-out figures for the full file and for one state per pair.

Recommended change: decide that a group of pairs is done by **saturation**, not by "the file was touched". A group
counts as done when a second pass and a held-out map add no new pairs to it. Groups are files for `Effect/*`
(1,095 small files, median 5 pairs) and finer units for the 8 shared files. Unreached groups keep 1–2
render-target states per pair. The tour's real gain is exact records for everything it reaches: overworld scenery,
dungeon rooms, both ages and the menus.

**Estimate:** about 20 hours of offline work, plus 10–13 hours of emulator time in 4 sittings. That makes 3–4 days
of wall-clock time. One full tour takes **6–9 hours** of emulator time and resumes map by map.

## TODO

The offline steps (1–6) need no emulator. The emulator steps (7–12) launch Lichii and move the shader
folder aside the way `exp.sh` does.

1. **Extract all 80 warp maps with `ootx`** (2 h, offline). Get the StartPos and DestinationAnchor actors, the
   `DungeonRoomArea` boxes, map extents and placements from `extractor/` (`ootx map GAME.nup <banc> …`). Forest Temple
   takes 1.2 s (verified: `extractor/README.md`), so all 80 should take minutes, not hours. 12 maps are already in
   `dump-out/`.
2. **Route planner** (5 h, offline). The per-map route depends on the map type:
   - **Overworld:** fly lanes about 40 units apart at 10–20 units above the ground.
   - **Dungeons:** visit the centre of every `DungeonRoomArea` on every floor.
   - **Boss stages:** go to the centre and fly one ring.
   - **Every route:** a 360° camera turn at each waypoint, and a low pass past each placed `Enemy_*`, `Npc_*`,
     `Obj_*` and `EftLoc_*`.

   Routes avoid sloperinaGZ's exit shapes (`data_exits`, 151 entries, and `data_exitshapes` in
   `refs/sloperina/src/ootgz/data.c`). Output: one JSON per map, holding the warp menu path, the spawn position,
   segments as stick vectors and frame counts, and checkpoints.
3. **Tour driver `tour.py`** (8 h, offline). It reuses `pad/dsu_server.py`, `pad.py`'s UDP protocol and the verify
   hook's frame counter and screenshots (`127.0.0.1:26799`, `count` and `shot`). Per map:
   1. Open the menu (R + right stick down) and navigate by index to *warps › places › category › map › spawn*,
      then press L.
   2. Confirm the warp from the `eden_log.txt` lines `warp: requested … to MAP / SPAWN` and
      `warp: the game reserved MAP`.
   3. Wait until loaded (step 4).
   4. Press L3 to levitate, fly the segments by frame count and turn the camera with the right stick.
   5. After each segment, check the position (step 5).
   6. When the map is done, wait 30 s, copy `lichii-cache.v2.bin`, and write `tour-state.json`.
   7. On a timeout or crash, kill Lichii, restart, load the save and continue from the next map.
4. **Wait conditions** (in step 3). Map loaded means all of these:
   - the hook's frame count is advancing;
   - 10 s with no `Graphics pipeline built` or `Compute dispatch waited` lines and no puller `waits on semaphore`
     lines;
   - frame time under 50 ms for 300 frames;
   - sloperinaGZ has found Link again. Its log shows `levitate: Link's physics record is …` after L3; a
     `Link's position not found` notice means retry.

   No frame advance anywhere (step 7). The hang timeout is 5 minutes with no new frame, not 10 s.
5. **Position check** (3 h, offline). `memwatch` cannot follow guest pointers (verified:
   `memwatch.py` docstring). It finds Link's actor by value from a known position, so `tour.py` calls
   `locate X Y Z` with the spawn coordinates from step 1, using a looser tolerance. After that, `show` reads the
   position every segment. Fallback: read the watches panel's digits from hook screenshots, which `verify.py`
   already does for one template. If Link is more than 15 units off the route, re-centre from the waypoint or
   re-warp to the spawn.
6. **Builder change and offline evaluation** (4 h, offline). See "The rebuild" below. Rerun `eval/filecheck.py`
   with a held-out cache.
7. **Smoke test** (1 h of emulator time). Set `frame_advance=0` (it is 0 today), `levitate=1`,
   `levitate_through_walls=1`, `levitate_move_speed=30` and `arrival_cutscenes=0` in
   `~/.local/share/lichii/sdmc/sloperinaGZ/settings.ini`, plus infinite health in the cheats. Boot once, then warp
   to a child overworld map, an adult one (this checks that the age follows the map), a dungeon and a boss stage.
   Measure the load time, the fps while flying, the levitate speed in units per game second, the camera turn rate
   per frame, and whether `eden_log.txt` can be tailed live.
8. **Pilot tour of 6 maps** (1.5 h of emulator time). Kokiri Forest (child), Hyrule Field (adult), Deku Tree, Fire
   Temple, Gohma, plus one map held out from training. Check the route timing, the resume after a forced kill, and
   how many new pipelines each map adds.
9. **Full tour of 80 maps** (6–9 h of emulator time, in 2–3 sittings, resumable). Then one pass that opens every
   pause-menu page and the item wheel (15 min).
10. **Second pass for saturation** (1 h of emulator time). Re-fly 6 maps with the route shifted by half a lane. A
    group that gains no pair counts as saturated.
11. **Gap passes** (optional, 1–2 h of emulator time).
    - Day and night: Sun's Song from the ocarina (the inventory menu can give the song), or find the time-of-day
      GameData field.
    - Arrival cutscenes on, for the boss stages.
    - Item use at one spot: sword, bombs, arrows, hookshot.
12. **Rebuild, prepare and validate** (1.5 h of emulator time).
    1. Build the file without the held-out maps.
    2. Prepare it. At about 50k records against the README's 311k in 105 min, this should take about 15–25 min.
    3. Run the `exp.sh`-style first-visit test at the held-out map: a warp from the save, then that map's tour
       route. Compare against the full 311k file and the everything-cached floor.

    Pass: compile work and time over 33 ms are no worse than with the 311k file, and the file fits Metal's
    default cache.

## The rebuild

Code read: `tools/nx2-precompile/py/build_precompiled.py` and `state_model_static.py` (verified by reading). Today
the builder writes three kinds of record:

- every recorded pipeline from `--train`;
- for every pair in `nx_pairs.json` plus the recorded pairs, `model.candidates(vs, fs, kt, kl, kf, kd)`: the most
  likely state, then one part varied at a time (`--static`: kf=6, kl=4, kt=2, kd=1);
- mesh and compute records.

The change:

- `--tour CACHE` (repeatable): recorded pipelines from the tour, added like `--train`. They also feed the model.
- `--done-groups FILE`: a JSON list of groups the saturation step marked done. Unseen pairs in those groups get no
  prediction. A group is the vertex shader's `coarse` file for `Effect/*`, `Layout2Shader/*` and the small archives.
  For the 8 shared files, file-level grouping cannot work: `fine` gives only 3 groups for `Model.Product.110`, one of
  which holds 12,458 pairs (verified, computed from `inventory.json`). Until a finer unit exists, those files are
  never "done".
- `--elsewhere kf[,kl,kt]`: the states for pairs outside done groups, default `1` (top state only). `2` adds the
  second render-target state; the fragment half is the costly one (README: about 200 ms against about 10 ms for
  the vertex half).
- Saturation (a new script, `saturation.py`): it reads the per-map cache snapshots and computes new pairs per group
  for pass 2 against pass 1 and for the held-out maps. A group is done when, over at least 3 visits, its last visit
  added nothing.
- 134 pairs have a vertex shader in more than one file (verified). Count such a pair as done only when every one
  of its files is done.
- A finer unit for `Model.bfsha` (optional, 1–2 days offline): map each model material's shader-assign options in
  the BFRES files to its program index. Each pair then gets a list of the models and actors that use it. That
  turns "done" into "every user was drawn in the tour", and it may show that many of the 12,458 variants are used
  by no material at all.

**Record counts.** Computed from `inventory.json`, `nx_pairs.json`, the three `cache*.fork-v54.bin` files and a
scan of `static.nx2prep`'s record keys, with today's caches standing in for a tour:

| Rule | Groups counted as exercised | Unseen pairs dropped | Pairs kept | Records, 1 state per kept pair | Records, full prediction kept |
| --- | ---: | ---: | ---: | ---: | ---: |
| Today's file | — | 0 | 33,253 | — | 311,091 |
| Any file with ≥1 seen pair (as proposed) | 74 | 19,485 | 12,647 | ~27,000 | ~137,000 |
| Same, files of ≤1,000 pairs only | 70 | 3,126 | 29,006 | ~43,300 | ~282,500 |
| Same, files of ≤200 pairs only | 66 | 679 | 31,453 | ~45,800 | ~302,000 |

Base in every row: 4,041 distinct recorded vertex/pixel keys, 6,209 mesh and other graphics records, and 4,058
compute records. The predicted vertex/pixel records in `static.nx2prep` come to 9.05 per pair (300,824 over 33,253). These counts are
from that 311,091-record file; the current full file is `static-v2` (292,535 records, see
[precompiled-file.md](precompiled-file.md)), so the ratios are close but not exact for it.
After a real tour, each pair the tour reaches moves from "kept" to "exact", at about 3.6 recorded keys per seen pair
today (4,041 keys over 1,121 pairs). If the tour sees 3,000–6,000 pairs, the 1-state file comes to about 45,000–65,000
records. At 2 states, add about 30,000. At the full file's 4.2 KB per record that is about 0.2–0.3 GB: under
Metal's 1 GiB per-file limit (its cache files stop growing at about 1.2 GB on disk; see
[metal-shader-cache.md](metal-shader-cache.md)) (**inferred**; prepared bytes per record vary).

## Evidence

### Controls available today

- **Warp** (verified: `refs/sloperina/src/ootgz/warp.c`, `menus.c`, `README.md`). Menu only: R + right stick down
  opens it, the D-pad moves, L selects, R + D-left goes back. The warp asks for the game's own
  `Dm_SY_BancChangeGo` event, and if that is refused, an armed fallback waits for Link to take an exit. Each warp
  writes `OutputDebugString` lines to `eden_log.txt` (verified in `research/logs/log-run3-hang-on-warp.txt`, 348.95–351.17 s): `warp
  to …`, `requested … to MAP / SPAWN`, `the game reserved MAP`. No other trigger exists. Writing GameData with
  `lichiimem wr` would mean finding the field addresses by scanning first (assumed workable, not needed).
- **Maps** (verified: `refs/sloperina/data/warps.json` and `src/ootgz/data.c`). 80 maps and 336 spawns: 16 child
  overworld, 21 adult overworld, 13 dungeons, 27 boss or mini-boss stages and 3 others (`EnemyMuseum`,
  `SageRoom`, `Demo_ShootingLocation_Tapestry_ED`). Interiors are inside their map's geometry (verified:
  `Shop_Inside_C` comes from `Market_Child`; `extractor/README.md` and the `dump-out/renders/cand_market_*` files).
  Warping to an `_Adult` or `_Child` map sets Link's age (verified: `docs/SCENE_CHANGES_AGE.md`, "the new map sets his
  age"); dungeons and boss stages keep the current age.
- **Noclip** (verified: `levitate.c`, `MANUAL.md`, `settings.ini`). L3 starts and stops levitate, X rises, B
  descends, and the left stick moves relative to the camera at 2–30 units/s. With "through walls" on, levitate asks
  for the game's ForceNoHit and moves Link through the controller's own position setter. The `FINDINGS.md` open
  problems section says the user confirmed passing a wall that had blocked him (verified by reading).
  Today's file has `levitate=0`, `levitate_move_speed=6` and `levitate_through_walls=1` (verified: `settings.ini`).
  - Levitate turns off when a warp starts ("exit taken …; off until the map loads"), so L3 must be pressed again
    after every load.
  - Flying into an exit's shape drops Link ("levitate off: loading zone"; verified: `levitate.c` around line 1030),
    so routes must avoid the exits.
- **Camera:** the right stick only, through `pad.py rs:x,y` (verified: `pad.py` docstring). The camera's memory
  (`0x84eb8068`) sits behind guest pointers, which memwatch cannot follow (verified: `memwatch.py`).
- **Position:** `memwatch.py locate X Y Z` and then `show` (verified by reading). It needs a known starting position
  after every load; spawn positions can come from step 1 (assumed accurate to within the tolerance).
- **Frame clock and screenshots:** the verify hook (verified: `verify/README.md`). The `count` UDP command, plus
  window captures that work while the window is behind others.
- **Map sizes** (verified: 5–95% extents of the placements in `dump-out/*/placements.json`). Roughly 75–310 by
  60–160 units, with up to about 180 units of height in dungeons. At the 30 units/s maximum, an overworld lane sweep
  is about 25–60 s of game time. Hyrule Field has not been extracted and is assumed to be several times larger.

### The warp hang

- **What is known** (verified: `research/logs/log-run3-hang-on-warp.txt`). The log comes from stock build 228, not the
  prebuild app.
  - At 333.7 s, `frame advance on` and `frame advance in pause screen on`.
  - At 348.95 s, the warp to Kokiri Forest. The game reserved the map 2.2 s later, and levitate lost Link's record.
  - Pipelines were still being built at 357.7 s.
  - At 359.7–359.9 s, four GPU channels had waited 2 s on semaphores.
  - **The log ends 11 s after the warp.** No present-summary line follows the warp: they come every 600 presents,
    about 20 s apart.
- **Most likely cause** (assumed, from `MANUAL.md` §4): sloperinaGZ's frame advance, not a hang. With frame advance
  on, the game pauses until the button is pressed ("While paused the game draws nothing"), and "a tap counts when
  you let go". The warp was chosen with **L**, the frame-advance button (`frame_advance_button=0`). If that L press
  was let go after the menu closed, it counted as a tap and paused the game during the load. The GPU semaphore
  waits fit a game thread stopped mid-frame. The README's own note that "a later black transition at 5 fps did
  recover", plus the 11 s cut-off, also fit a slow first-visit load that was judged too early. This was not
  reproduced.
- **Avoidance.** Keep `frame_advance=0` (it is today; verified). Wait for 5 minutes of no new frames before calling
  it a hang. Treat puller semaphore warnings as "loading", not as failure. Recover by restarting and resuming from
  `tour-state.json`. If it ever recurs with frame advance off, take the frame count and a screenshot before killing,
  and press L + L3 (the frame-advance release) first.
- **Not blocked.** Even a real hang costs one restart: a boot is about 3–5 min (assumed from verify's 5–8 min per
  run, which includes a 3,000-frame route).

### What a tour records and what it misses

- **Pipelines are made at draw time.** Verified from source and log: `vk_rasterizer.cpp` prints `Draw skipped (no
  pipeline)` while the pipeline builds on the GPU thread. Pipelines built from the precompiled file are still
  written to `lichii-cache.v2.bin` with their real environments (verified: `vk_pipeline_cache.cpp` around
  4983–5075). `CreatePrecompiledGraphicsPipeline` falls through to the same `cache_v2->Writer().Append(Graphics…)` as
  a translated pipeline. So the tour can run with a prediction file already prepared and still record exact
  entries. `Used` records are written per session (`SaveUsedPipelines`, at least 64 pipelines), and the cache is an
  append log whose reader stops at a short read (verified: `lichii_cache.py`). Per-map snapshots of the file
  therefore attribute records to maps.
- **"Only what the camera draws": partly verified.** Draw-time creation is verified. That the game culls objects
  out of view is **assumed**: it is standard, and the canyon alone lacked 192 of 509 pipelines from another
  session's cache. Exceptions to plan for:
  - The shadow pass (`agl_technique_shdw`, 9 of 957 pairs seen) draws casters out of view.
  - LOD and distance fades need a close pass as well as a far view.
  - Dungeons draw by room (`DungeonRoomArea`), so every room must be entered.
  - Actors appear only when Link is near (state 6 or 3 "waiting to appear"; verified in `sloperina-findings.md`).
- **Camera path per map:** at each waypoint, a full horizontal turn and one look up and down. Lanes close enough
  that every placed actor is passed within its appear radius (assumed about 20–30 units).
- **Gaps, with pair counts from the Effect files** (verified, per file-name prefix):

| Gap | Pairs | Proposal |
| --- | ---: | --- |
| Cutscene effects (`Dm_*`) | 5,501 | Not reached; keep predictions. Optionally, boss arrivals with cutscenes on |
| Enemy effects (`Enemy_*`: attacks, deaths) | 2,952 | Partly: low passes trigger appearance and attacks (infinite health); deaths not covered. Keep predictions |
| Bosses (27 stages) | in the above | The arena is drawn on arrival; fights not covered |
| Item and weapon effects (`Weapon_*` 172, `Item_*` 118) | 290 | Gap pass: use each item at one spot |
| Menus, UI (`MergeShader`, 57 of 113 seen) | 113 | Open every pause page and the item wheel once |
| Day and night, weather | unknown | Sun's Song pass on the 6 maps with a night (assumed: day/night as in the original) |
| Child and adult | — | Covered: both versions of every overworld map are warp targets |
| Story-state variants of one map (e.g. Water Temple levels, `ForestTemple.bpvsts` variants) | unknown | Not covered; keep predictions |

### Counts the plan rests on (all verified by computation)

- 1,121 pairs seen across the three caches, all in `nx_pairs.json`. Cache 1 is inside cache 2 (670 shared of 670);
  cache 3 added 362 new pairs. Each session still adds about 30% new pairs, so nothing is near saturation.
- 33,253 pairs: 15,358 distinct vertex shaders and 21,269 distinct pixel shaders. 20,390 pixel shaders were never
  seen.
- Pairs per vertex shader's `coarse` file: 1,115 files, 74 with a seen pair. Another way of assigning pairs to files gives
  894 and 73 (the figures in `precompiled-file.md`); the conclusions do not change.
- 8 files hold 18,806 of the unseen pairs in exercised files. The 1,095 `Effect/*` files hold 13,987 pairs.
- `static.nx2prep`: 311,091 records, of which 300,824 vertex/pixel, 6,209 other graphics and 4,058 compute.
- Scripts used: `perfile.py`, `prep.py`, `analyze.py`, `fine.py` and `est.py` in this session's scratchpad. They only
  read `eval/out-all/` with `lichii_cache.py`.

### Time per map (assumed, to be measured in step 7)

- Load: 1–3 min. It is the cold first-visit compile: the canyon cost 175.6 s of worker compile and a 20.1 s worst
  frame, falling to 7.3 s and 3.8 s when prepared.
- Flight: 2–4 min for overworld maps, 5–8 min for dungeons, about 1 min for boss stages, at 30–50 fps.
- Total: 16 + 21 overworld × about 4.5 min + 13 dungeons × about 8 min + 30 small × about 2.5 min = about 345 min,
  plus restarts. Hence 6–9 h.

## Risks, ranked

1. **The rule's payoff.** Without a finer unit than the file for `Model.bfsha` and the agl and Terrain archives, the
   tour can never safely drop the bulk of the predictions. The smaller file then rests on "1–2 states elsewhere",
   which loses fragment coverage for content the tour misses: cutscenes, enemy effects and story variants. The
   held-out test (step 12) must decide this.
2. **The build the tour records with.** Keys carry device and build bits. `exp-pred` was void because of that
   (verified: README). The tour must run on the same app and build that will use the file, and that is not the
   default `/Applications/lichii.app` (the practice build has no PR #1366).
3. **Flight control is open-loop.** Levitate speed, camera turn rate and collision side effects are untested here,
   and wall handling is still an open problem in `FINDINGS.md` §8. Drift, getting stuck, or an exit taken by mistake
   all cost a re-warp. Mitigation: position checks per segment (step 5) and exit-shape avoidance.
4. **Finding Link after each load.** `memwatch` needs a starting position, and levitate's own record search can
   fail ("Link's position not found"). Mitigation: the screenshot fallback, re-warping to the spawn.
5. **Crashes and the cache under kill -9.** Records queued on the serialization thread can be lost when Lichii is
   killed (assumed). Mitigation: a 30 s quiet wait and a snapshot before every kill. The append log survives
   truncation.
6. **Metal cache cap during the tour.** With the default cap, a fully prepared 311k file is mostly evicted (verified:
   README), so the tour runs near cold and slowly. That only costs time.
7. **Machine load.** Other builds running at the same time slow the emulator (verified: verify README, load average up
   to 54). The tour holds the verify lock and should run when nothing else is compiling.

## What I could not check

- Anything at run time: load times, fps while flying, levitate speed, camera turn rate, whether `eden_log.txt` can be
  tailed live, and whether a warp to every one of the 336 spawns works. `warp.c` notes crashes to warp-song pads that
  were fixed but "not yet confirmed in game".
- Whether the installed sloperinaGZ build matches `refs/sloperina` at `bf46f43` ("Release 0.0.7"). The
  `FINDINGS.md` there describes 0.0.8 and 0.0.9 fork test builds, while `settings.ini` and the log only show that a
  1.1.1-compatible build runs.
- The warp-hang cause: inferred from the manual and the log, not reproduced.
- That the game culls by camera, and the actor appear radius.
- Day and night in this remake, and the GameData field for time of day.
- Hyrule Field's size and the other 68 maps' extents (not extracted).
- Whether per-fragment deduplication is safe: one record per pixel shader × render-target state instead of per
  pair, which would cut "elsewhere" records by at most about 36% (21,269 pixel shaders against 33,253 pairs). It
  depends on whether a fragment's MSL depends on the vertex stage it is paired with.
