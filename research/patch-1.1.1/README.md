# What patch 1.1.1 changed

A comparison of version 1.0.0 with 1.1.1 of the 2026 Ocarina of Time remake, made from one dump that holds both:
every data file, and the executable function by function.

- **In short:** 1.1.1 is Zelda Notes support, groundwork for a Master Quest add-on, and about twenty targeted
  fixes. Seven of the fixes bear on glitches runners use. The world is untouched: no actor placement, no
  navigation mesh and none of the collision Link walks on changed.
- **Order of this page:** [what matters to speedruns](#1-what-matters-to-speedruns), then
  [what is interesting but does not](#2-interesting-but-not-for-routes), then [the rest](#3-the-rest-briefly).
- **How to read it:** each claim is marked *code* (read in both versions' machine code), *data* (decoded from the
  game's files) or *inferred*. **Nothing here was tested in game**: 1.0.0 cannot be run in this repository's
  emulator setup, so every "1.0.0 did X" is a reading of its code.
- **Left out on purpose:** memory addresses, structure offsets and the comparison tooling.
- The update is cumulative, so 1.1.0 cannot be told apart from 1.1.1.

Glitch names are those of [the glitch list](../../OOT-GLITCHES.md).

## 1. What matters to speedruns

| Glitch | Status in 1.1.1 | Why |
| --- | --- | --- |
| [Hookshot storage](#hookshot-storage) | fixed | the hook's stuck state now ends when its constraint has lost its bodies |
| [Fall damage cancel](#fall-damage-cancel) | fixed in its usual form | the height a jump started from is refreshed on the ground |
| [Save or void-out below a floor](#three-boxes-where-the-restart-point-freezes) | fixed at three spots | the restart point is frozen inside three boxes |
| [Three standing spots](#three-invisible-walls) | blocked | three invisible walls, added from code |
| [Ragdoll warping](#ragdoll-warping) | slowed, not removed | the pull is capped at 30 units per second |
| [Cucco teleport](#cucco-teleport) | one route closed, glitch survives | the cucco's "return to safe ground" got two checks |
| [Deku Stick](#deku-stick) | three small fixes | drawing with none, a free stick, a stuck stick |
| Jumpslash cancel | **untouched** | its limit is a different value, which the patch does not write (code) |
| Actor jump, hover jump, hitstop launches | no change found | (code) |
| Chest minigame storage and what is built on it | no change found | (code, data) |

### Hookshot storage

*Listed as 1.0 only.* This is the patch's one change to the hookshot, and the code explains part of the glitch
but not all of it.

**How a pull works (code, data; same in both versions).**

- The hook is its own object and is reused for every shot. When it hits something, it records what it hit (the
  physics body and the point on it) and switches to a "stuck" state.
- In that state the hook ties its own body to the body it hit with a physics constraint. The constraint only
  holds the hook in place.
- Link's hookshot action sees that the hook is stuck and climbs in a straight line to wherever the hook is. That
  is why a stored pull goes through walls: it is a move to a point, not a physical pull.

**Where the "storage" is (code).** The hit record on the hook is never cleared: not when the hook retracts, not
on a cancel or a miss, not on a scene change. It is left behind after every shot.

**What "interrupted on the frame it attaches" does (code, data).** Each frame the hook first obeys a request from
Link and only then makes its own pending switch. If Link's hookshot action is ended early on the hit frame (a
fall, a slide, an unequip, damage), it posts a cancel, the hook obeys that instead of sticking, and the pull
never happens. The hit record stays.

**The fix (code).**

- **1.0.0:** the stuck state never checked that the constraint's bodies still existed. If a body was gone (the
  thing that was hit had been unloaded), the state ran on anyway for up to 180 frames while Link climbed to the
  hook.
- **1.1.1:** the stuck state ends at once when the constraint is active but the hook's side of it has no body,
  which is also what happens when the stored target no longer exists.
- Nothing else in the hookshot's code or data changed.

**What the code does not explain.**

- *Why the next shot sticks at the old point.* Not found. Only a hit during the current shot leads into the
  stuck state, and a new shot does not start from where the hook was left: the hook is put to sleep after each
  shot, woken at Link's position for the next, and its body is moved to the muzzle before it flies. The leftover
  hit record is never read again.
- *Why storage fails everywhere on 1.1.1.* Runners report it never works, same room included. By the code, a
  stored pull that gets as far as the stuck state has both bodies present, and the patch would not end it. So
  the change that kills storage may be elsewhere, or the stored pull may never reach that state in the way the
  code suggests. The general code that keeps an object's position in step with its physics body was also read
  in both versions and is unchanged in behaviour. Reading the code further will not settle this; a memory read
  during a stored release, on both versions, would.
- *The crash on another map in 1.0.* It is not the state the patch ends, which is safe in itself. The code that
  can fault uses pointers left over from the previous pull, and that code is unchanged in 1.1.1.

The fix agrees with the comparison *FantaTanked* and *ontrigger* posted on 17 November.

### Fall damage cancel

*No version listed.* The game keeps two things for fall damage (code): a "fall start" position, which a landing
is judged against, and a "take-off height". On the ground the fall start follows Link. During a jump, side hop,
backflip or jumpslash it follows him only while he is more than 0.8 above the take-off height, which is how a
jump from a ledge does not count the rise as a fall.

- **1.0.0:** it was set only when one of those moves started.
- **1.1.1:** it is also set to his current height on every frame he stands on the ground, climbs, hangs from a
  ledge, rides a cucco glide or is in deep water.

In 1.0.0 the take-off height could therefore be stale: jump on low ground, walk up high without jumping, walk off
a ledge and jumpslash mid-fall. Link is far above the old take-off height, so each jumpslash frame moves the fall
start to where he is and the landing does no damage. In 1.1.1 the take-off height is the ledge he walked off, so
the landing is judged on the full drop (inferred from the code). Height gained entirely in the air since the last
take-off should still work.

The **jumpslash cancel** is not affected: its lift is limited by a different value, which the patch does not
touch (code).

### Three boxes where the restart point freezes

Link has a "restart point": the last safe place he stood. The game saves it as his position, returns him to it
after a fall into a void or after drowning, and hands it to Farore's Wind (code, same in both versions).

1.1.1 adds one rule (code): inside three boxes, hardcoded by scene name and coordinates, the restart point is not
updated, so it stays at the last place outside the box.

| Scene | x | y | z | What is there (data) |
| --- | --- | --- | --- | --- |
| Water Temple | −11 to 15 | 82 to 99 | −15 to 6 | the central room below its top floor |
| Collapsing Ganon's Castle | −38.6 to −16.7 | 218.9 to 227.6 | −30.4 to −0.5 | under the Ganondorf arena, down to the rubble |
| Collapsing Ganon's Castle | −31.9 to −28.1 | 219 to 222.2 | 3.7 to 9.7 | a small pocket beside it |

In 1.0.0, standing in one of these places made it the restart point, so a save and reload, a void-out or a
drowning afterwards put Link back there. In 1.1.1 he goes back to where he was before entering it. This bears on
save/load respawn manipulation at exactly these spots; everywhere else the rule is unchanged.

### Three invisible walls

1.1.1 spawns three walls from code every time an area loads; the only condition is the scene (code). Each is an
invisible box that stops Link and nothing else: NPCs, enemies and the camera pass through (data). They are not in
the map files, which is why a comparison of the maps shows nothing.

| Scene | Base at | Size | Where (data) |
| --- | --- | --- | --- |
| child Market | (−17.8, 108.0, 4.1) | 3.5 × 4 × 15.8 | fills the space over the Bombchu Bowling Alley's porch roof, up to the main roof's eave |
| child Market | (4.5, 100.0, 19.8) | 1.8 × 4 × 1.2 | behind the market stall, in a notch of the stall's own invisible wall, against the house front |
| adult Hyrule Field | (−52.4, 156.8, 189.9) | 1.7 × 4.2 × 0.8, turned 12° | on the front gable of the Lon Lon Ranch house, over the ledge between the loft windows |

What each one blocks (data, from a reachability check on the maps; the purposes are inferred):

- **Bowling alley roof.** The porch roof cannot be walked onto; it needs a glitch climb. From it the whole
  bowling-alley roof opens, but that roof is an island: every way down leads back to the street, with no loading
  zone and no void. Players on 1.1.1 still get onto Market roofs by other routes, so this closes one way up only.
- **Stall.** The wall covers the exact spot the stall-keeper walks to, and Link and that NPC can push each other.
  It is not a softlock: the pocket is open to the street. It most likely stops Link blocking the NPC or being
  pushed into the stall.
- **Lon Lon gable.** The ledge has less headroom than adult Link under the roof, right against a solid wall with
  a tall room behind it: a place to be squeezed through the wall.

No source says why they were added, and none of the three leads to a loading zone, so they are unlikely to
matter to a route. *oussama* reported the three walls on 17 November.

### Ragdoll warping

*Listed on 1.0.* When Link ragdolls, his body is driven toward the ragdoll's position.

- **1.0.0 (code):** the body was asked to reach the ragdoll in one step, at any speed, so a ragdoll far away
  pulled him across the map.
- **1.1.1 (code):** the speed is capped at 30, or 60 while the ragdoll falls fast. The Bongo Bongo rolling ragdoll
  is exempt.
- **Why the warp exists (code, same in both versions):** the step that makes the body follow the ragdoll stays
  armed until a full ragdoll clean-up runs. One reset path clears the ragdoll's type without that clean-up, after
  which every later clean-up does nothing. If Link is then moved (respawn, warp, load), the armed step drives him
  to where the ragdoll was left. A new big hit cleans up properly, which is why a bomb tumble ends it.
- **So (inferred):** 1.1.1 slows the warp and does not remove it. The cap is per second, about 0.5 to 1 unit per
  frame, so a 300-unit pull takes about 10 seconds instead of one frame. Whether the slow pull still passes
  through walls was not determined, and no runner test on 1.1.1 was found. A ragdoll started by Bongo Bongo's
  rolling hit would be uncapped.

### Cucco teleport

*Still reported on 1.1.1.* An angry cucco that left the navigation mesh used to be placed straight at the nearest
mesh edge (data). In 1.1.1 it moves only if there is ground under that point and a clear line from the cucco to
it, and it goes to the ground. The glitch has survived, so another route to it exists.

### Deku Stick

- Drawing a Deku Stick now checks that the pouch has at least one (code). 1.0.0 drew it with none.
- A stick that is used up while its object is already gone is now still taken from the pouch (code). In 1.0.0
  that consumption was skipped (inferred: a free stick).
- A stick left in Link's hand after the inventory changed is now removed in one equipment mode (code; the mode
  was not identified).

### Smaller changes a runner could meet

| Area | Change | Basis |
| --- | --- | --- |
| Dropped items | picking up an item while it is still bouncing now ends the bounce at once and restores the item's normal physics settings. In 1.0.0 that happened only when the bounce ended by itself, so an item grabbed mid-bounce was carried with bounce settings (inferred) | code |
| Swimming | floating is switched back on when an event hands control back to Link. In 1.0.0 an event that began while floating was off left him not floating afterwards (inferred) | code |
| Hammer switches | a hit counts only while the switch has registered being struck, and that state is cleared when the switch's check starts | code |
| Ganondorf, Phantom Ganon | a second piece of one lightning shockwave now counts as its own hit instead of being merged into the first | code, data |
| Ganondorf | his death animation stops at frame 44 of 93; Navi's prompt is suppressed once he is dead in the boss rush | data |
| Camera | when climbing starts while the camera was being held in place, the climb camera now cuts straight to its position and holds off its slope correction for about a second; in 1.0.0 it swept in from the held position | code, data |
| Navi | one hint, for a rematch, is handled as a special case | code |
| Horse race | after time ran out, the race's event script waited forever; it now ends | data |
| Loading | for three area loads out of every 501, the neighbouring area is not pre-loaded, so those loading zones take a full load | code |

## 2. Interesting, but not for routes

### Master Quest is half built

The mirrored Master Quest mode has been in the game since 1.0.0, switched by a per-account setting that nothing
turns on. 1.1.1 adds an ownership check for a paid add-on (without it the mode is forced off), the `_MQ` scene
names of thirteen dungeons, per-room save records for eleven of them, and 88 event flags, of which 83 names were recovered:
they show cow switches in Jabu-Jabu, 22 switches in the Fire Temple and the Longshot in the Water Temple. No Master Quest map is shipped. The full
account is in [../master-quest/README.md](../master-quest/README.md).

### Zelda Notes is most of the patch

The game now keeps a log (code): a history of events (items gained and lost, scene changes, songs played, saves),
a trail of where the player has been, and lists of watched save values. Calls that feed it were added next to
unchanged logic all over the game: every way of getting an item, attacks and magic, fishing, rupees, milestones,
location and sign discovery, boss times. Eight cutscenes request a screenshot.

- The log is stored in the options save file, which grows from 1 KB to 44 KB and is shared by all save slots.
- The history and the trail each hold 1,024 entries; up to 640 save values are watched.
- Nothing read back from it affects play (code). One thing looks like gameplay and is not: a Hyrule Field Piece
  of Heart chest is not counted as a milestone until the fairy note next to it has been read.
- In the final battle, each temporary save is now followed by a write of that options file (code, data). Progress
  data is not involved.
- It also brings a network client, leaderboard calls, a parental-control age check, new option screens and the
  navigation marker models.

### Fixes for things nobody listed

| Area | Change | Basis |
| --- | --- | --- |
| Lock-on | with the targeting option set to Switch, the game re-locks Link onto his target after an event (a talk, a sign). If that target is not an enemy, 1.1.1 keeps his shield down until the lock is dropped; 1.0.0 raised it as soon as an enemy became the top target. The sword and items are not affected | code |
| Projectiles | when an actor is unloaded, its fast-projectile bodies (arrows, the hook) are now also removed from the physics world; 1.0.0 could leave one registered | code |
| Ocarina | putting the ocarina away on the same frame as opening the audio-input help no longer ends the session under the help screen | code, data |
| Jabu-Jabu | the elevators keep a non-player rider at steeper contact angles, and after five seconds of contact until it ends (inferred: for Ruto) | data |
| Ganon | his swords no longer push the camera; the boss rush resets a leftover flag between attempts | data |
| Horse race | fence-jump messages stop once the race is finished | code |
| Dampé's digging game | one path clears a leftover flag | data |
| Enemies | one more case in which an enemy switches to "lost sight of target" | code |
| Disappearing actors | a model attached to an actor that disappears is now detached from that actor's shared draw settings at once (it looks like a shared fade); 1.0.0 kept it attached until the actor was gone | code |
| Cutscenes | the camera eases out after two cutscenes (Dodongo's Cavern, Goron City); one floor-contact effect was removed from a Gerudo Fortress cutscene; dialogue text can fade in a range of characters | data, code |
| Pause map | its view is clamped to the map's edges | code |
| Models | nine actors have new bounding boxes, which decide when they are drawn (Deku Baba, ReDead, Gohma's eggs, Dodongo, the diving game) | data |
| Item shortcuts | only the Deku Stick on ZR still tells the item shortcut screen that it hit something; in 1.0.0 every ZR item did. What the screen does with that was not determined | code, data |
| Text | "opals" became "topazes" in one Gerudo line | data |

## 3. The rest, briefly

- **Data files:** 184,303 of about 186,000 are identical. 1,406 effect files changed only by recompiled shaders;
  715 new culling files cover three scenes that had none (adult Kakariko, its alternative, and the adult Zora's
  Domain alternative); 160 duplicate voice files were dropped.
- **Executable:** about 247,000 functions on each side, of which 3,290 have changed instructions. Most of those
  are the compiler: a different choice of what to inline, a destructor pattern rebuilt in about 2,000 classes,
  blocks in another order.
- **Audio and effects:** one sound's volume curve changed; the ocarina's moving effect lost two emitters; four
  navigation cursor effects are new.
- **Graphics:** work on rendering several views, one new render pass, ten more never-culled scenery pieces in the
  Water Temple and Dodongo's Cavern (a pop-in fix), handheld fog scale in three scenes, water fog in the adult
  Market.
- **Libraries:** the system SDK went from 22.2.5 to 22.2.8.
- **Languages:** Thai was added to the language list, with no text yet.

## What was not settled

- Nothing was run in game.
- Hookshot storage: how the next shot re-enters the stuck state, why it fails even in the same room, and the
  cause of the crash.
- Why each of the three invisible walls was added; nothing useful was found behind any of them.
- Whether the slowed ragdoll warp still passes through walls.
- About 440 small leftover functions and a few very large rebuilt ones were classified by group, not read line by
  line.
