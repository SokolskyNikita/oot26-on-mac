# The infinite jumpslash, played frame-perfect by a script

The [jumpslash cancel](../../OOT-GLITCHES.md#jumpslash-cancel) (found by *Ataappi*, 7 Nov; mechanics first written up
by *nathanisbored*) lets child Link climb without limit by chaining jump slashes in mid-air. This page is the chain
as a fixed-timing script that sloperinaGZ plays inside the game, why it works, and why its numbers are what they are.

- **The script:** [infinite_jump.txt](infinite_jump.txt). From any spot in Kokiri Forest it puts Link on the start
  spot, draws the stick and climbs 60 loops: +42 m in 50 s.
- **Video:** [the script in the game, with sound](https://www.youtube.com/watch?v=TQp3hR4JfWk) (64 s): Link is put on the
  start spot, gets ready and climbs 60 loops.
- **Measured** on game 1.1.1 in this repository's pinned Lichii build, child Link, Kokiri Forest. Claims marked
  *code* were read in the game's executable; the rest were measured frame by frame.

## Running it

It needs sloperinaGZ with remote control, which is open upstream as
[PracticeROM/sloperina#48](https://github.com/PracticeROM/sloperina/pull/48),
[#49](https://github.com/PracticeROM/sloperina/pull/49) and [#50](https://github.com/PracticeROM/sloperina/pull/50)
(the script uses `repeat`, `input`, `place` and `status`).

1. Game 1.1.1, child Link in Kokiri Forest, the Deku Stick on ZR and the Boomerang just right of it in the item
   wheel. No normal jump (X) or sidehop since the title screen (see [the cap](#the-cap)).
2. **settings > remote control** on.
3. `python3 tools/remote.py --timeout 120 < infinite_jump.txt` from the sloperina checkout. It writes the script to
   `sloperinaGZ/remote/cmd.txt` on the SD card and prints each line's result.

The script does its own setup: `place` puts Link on the start spot facing away from the Kokiri, B then ZR leaves the
stick in his hand whatever he held, and a ZL tap puts the camera behind him. Sent exactly as published, from empty
hands, it climbed from y 110.36 to 152.38.

## Why it works

1. A normal jump (X) or a sidehop stores a **cap**: the height that jump is meant to peak at. A freshly loaded Link
   has none. *(code; measured: one X jump set the cap to exactly y + 0.7)*
2. A jump slash started in the air lifts Link by up to 0.7 m, and never above the cap, but only while he is still
   rising. The lift **replaces** his vertical speed with the take-off speed of a fresh 0.7 m jump: 6.13 m/s.
   *(code; measured)*
3. A jump slash can't restart itself. Changing the item on ZR ends it on the next running frame, and Link drops into
   a fall. *(code; measured)*
4. From a fall, the next attack press starts a new jump slash, with no height or speed condition. *(code; measured)*
5. So: slash, swap the item away, swap it back, slash again before the top of the rise, repeat. The item wheel
   freezes the game while it is open, so the inputs have all the time they need, and with no cap there is no height
   limit.

The sword doesn't work: a sword slash can't be ended in the air. The weapon only has to be back on ZR, not drawn.

### The cap

The cap is an absolute height and carries between maps. Returning to the title screen clears it, and so does a
change of age. A jump slash from the ground and a backflip don't set it. With a cap, the chain stops at it.

## The sequence

The script's loop, at 60 frames a second. "Running" frames are frames the game advances; frames with the wheel open
are paused.

| | Frames | Inputs | What happens |
| --- | --- | --- | --- |
| Opening | 3 | none | |
| | 2 | ZL, stick forward, A | lock-on jump slash from the ground, 5.5 m/s up |
| | 2 (`after_a`) | ZL, stick forward | Link rises |
| | 8 (`menu_wait`) | R | the wheel opens; the game is paused from 2 frames in |
| Loop | 1 (`select`) | R, stick right | the Boomerang highlighted |
| | 1 (`settle`) | R | |
| | 12 (`unequip`) | none | the wheel closes for 9 frames, then 3 running frames: the stick leaves Link's hand, the slash ends, he falls |
| | 8 (`menu_wait`) | R | the wheel again |
| | 1 (`select`) | R, stick left | the Deku Stick highlighted |
| | 1 (`settle`) | R | |
| | 11 (`zr_gap`) | none | the wheel closes for 9 frames, then running frames |
| | 1 | ZR | the next jump slash: launch at 6.13 m/s |
| | 2 + 4 (`ascent`) | none | Link rises |
| | 8 (`menu_wait`) | R | back to the top of the loop |

A loop is 50 frames: 34 paused, and 11 running frames between one launch and the next. It gains 0.694 m up and
0.93 m across. Measured: 120 of 120 loops launched exactly 50 frames apart, +83.9 m.

### What each value allows

Each value a frame at a time, 8 loops a run, the others as in the sequence:

| Value | Chains at | Fails at |
| --- | --- | --- |
| `after_a` | 1 to 6 | 7 |
| `menu_wait` | 8 and up | 7 |
| `select`, `settle` | 1 and up | |
| `unequip` | 10 to 13 | 14 |
| `zr_gap` | 9 to 12 | 8, 13 |
| `ascent` | 1 to 5 | 6 |

`unequip`, `zr_gap` and `ascent` each add one running frame between launches per frame, and it is that total that
decides the height, whichever value supplies it. Each frame of `menu_wait`, `select` or `settle` costs two paused
frames a loop (the wheel opens twice) and changes nothing else.

## Height per loop

With N running frames between launches, a loop gains the sum of N + 1 position updates starting at 6.13 m/s and
dropping 0.4833 m/s each: `(6.130·(N+1) − 0.4833·N·(N+1)/2) / 60` metres *(code)*. The measured gains match it to
the millimetre. A loop is 39 + N frames with the shortest wheel times.

| N | Up a loop (formula) | Measured | Frames a loop | Up rate | Across rate |
| --- | --- | --- | --- | --- | --- |
| 5 | 0.49 m | 0.492 m | 44 | | |
| 7 | 0.59 m | 0.592 m | 46 | 0.77 m/s | 0.82 m/s |
| 10 | 0.68 m | 0.681 m | 49 | 0.83 m/s | 1.04 m/s |
| 11 | 0.69 m | 0.694 m | 50 | 0.83 m/s | 1.11 m/s |
| 12 | 0.70 m | 0.700 m | 51 | 0.82 m/s | 1.18 m/s |
| 13 | none | doesn't chain | | | |

N = 11 is the script's choice: the best up rate within 0.001 m/s, 95 % of the best speed across, and one frame
inside N = 12, past which a launch comes after the top of the rise and gives nothing.

## Doing it by hand

Each was run as a variant of the sequence, 8 loops:

| Variant | Result |
| --- | --- |
| ZL let go after the opening | chains, same numbers |
| One ZR press held 6 frames, begun once the game runs | chains, same numbers |
| The stick tilted once the wheel is open and kept tilted until R is let go | chains, same numbers |
| R together with the ZR press | doesn't chain |
| ZR held from while the wheel is closing | doesn't chain: the press has to come while the game runs |
| The stick already tilted when R goes down | doesn't chain, and leaves the Boomerang on ZR |

**The slack.** A loop needs about 4 running frames however fast the inputs are, and lifts up to N = 12. So about 8
frames (133 ms) a loop are shared by the three inputs made while the game runs: R after the launch, R after the
swap-off (not before 10 frames from letting R go), and ZR after the swap-back (not before 9). Early costs height;
late past N = 12 loses the launch.

## On a console

Not run on a console yet.

- **What carries over:** the game counts in frames. The wheel pauses the game 2 frames after R and runs again 9
  frames after R is let go, at 57 and at 75 frames a second alike, so the console has the same counts.
- **What doesn't:** the controller's and the console's input delay, which is unmeasured and may not be a whole
  number of frames, and dropped frames, which shift everything after them.
- **To try:** measure the delay once (film R's release and the wheel closing at 240 frames a second), subtract it
  from `after_a`, `unequip` and `zr_gap`, then find each value's edges a frame at a time and sit one frame inside
  the late edge.
- **Reading a run from video:** the gain per loop gives N from the table above (0.59 m is 7, 0.69 m is 11).
  sloperinaGZ's watches show y, y speed and the cap ("jump height") directly.

## What breaks a run

- **An X jump or a sidehop since the title screen:** the chain stops at the cap.
- **A talkable NPC within ZL's reach:** ZL targets them and A talks instead of slashing. The script's start spot
  faces away from the Kokiri.
- **The camera not behind Link:** the opening becomes a side step (4.1 m/s up) and the chain never starts.
- **Too many running frames in a loop:** past 12, the launch gives nothing.
- **The stick not on ZR, or the Boomerang not right of it:** the swap picks the wrong item.

## Open

- Why the wheel takes 9 frames to close and the game pauses 2 frames after R: measured, not read in the code.
- A run facing 259° was stopped at loop 92 (y 174.2) and Link was put back on the start spot; the map's outer air
  wall goes up to y 187.1. A run facing 250° passed that point and reached y 194.3 in 120 loops.
- The console's input delay.
