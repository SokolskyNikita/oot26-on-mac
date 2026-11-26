# Master Quest in the 2026 remake: what the game already contains

What versions 1.0.0 and 1.1.1 of the 2026 Ocarina of Time remake reveal about its unreleased Master Quest mode.
It comes from the comparison of the two versions in [../patch-1.1.1/README.md](../patch-1.1.1/README.md).

- **In short:** the mode itself (a mirrored world with its own save slots) has been in the game since 1.0.0.
  1.1.1 makes it paid add-on content and adds the save records for thirteen Master Quest dungeons. The dungeons
  themselves are not in the game's files yet.
- **How to read it:** each claim is marked *code* (read in the machine code of both versions), *data* (decoded
  from the game's files) or *inferred*. Nothing was tested in game.
- **Left out on purpose:** memory addresses and structure offsets.

## How the mode works

*Code, the same in both versions unless noted.*

- **One setting per account.** It is stored in the account's save file, not in a save slot, so it applies to
  every slot of that user.
- **The world is mirrored.** With the setting on, the game flips the stick, the camera input and Link's
  movement, sets a graphics flag, and swaps the left and right audio channels (the audio part is inferred).
- **Separate saves.** The setting selects a second set of save slots, so Master Quest files do not overwrite
  normal ones.
- **Separate dungeon maps.** A scene change appends `_MQ` to the scene name, so each Master Quest dungeon is its
  own map and not a variation of the normal one.
- **Screens.** In 1.1.1 the map screen is mirrored in every map mode (1.0.0 mirrored it in one), and the
  pause-menu and inventory models of Link are no longer mirrored.

## How it is gated

*New in 1.1.1, code.*

- At boot the game asks the system which add-on content is owned and records whether add-on 1 is.
- Applying the setting now checks that record. Without the add-on, the mode is forced off and the stored
  setting is cleared.
- A new query lets the game's scripts ask whether the add-on is owned (always yes on a development build). No
  script in the shipped files uses it yet.
- The scene tables can be replaced by a newer variant when the add-on is owned and a version check passes. No
  such file is shipped.
- Nothing in either version's files turns the setting on: the screen that selects the mode is not shipped.

**With an edited save file (inferred, untested).** In 1.0.0, setting the value by hand would boot the game in
mirrored mode with the second set of save slots, and entering a dungeon would ask for a map that does not exist.
1.1.1 clears the value at boot when the add-on is not owned. Whether that check always finishes before the mode
is first applied was not determined.

## Which places get a Master Quest version

*Code and data.* Thirteen scene names get the `_MQ` suffix:

| | |
| --- | --- |
| Inside the Deku Tree | Shadow Temple |
| Dodongo's Cavern | Spirit Temple |
| Inside Jabu-Jabu's Belly | Bottom of the Well |
| Forest Temple | Ice Cavern |
| Fire Temple | Gerudo Training Ground |
| Water Temple | Inside Ganon's Castle |
| | Collapsing Ganon's Castle |

Hyrule Castle, the outside of Ganon's Castle and the final battle are explicitly exempt. The overworld has no
second version: it is the same maps, mirrored.

## The same rooms, rearranged

*Data.* 1.1.1 adds a per-room progress record for each room of eleven Master Quest dungeons. Every dungeon has
exactly the room count of its normal version:

| Dungeon | Rooms | Dungeon | Rooms |
| --- | ---: | --- | ---: |
| Deku Tree | 13 | Shadow Temple | 32 |
| Dodongo's Cavern | 23 | Spirit Temple | 34 |
| Jabu-Jabu | 19 | Bottom of the Well | 13 |
| Forest Temple | 31 | Gerudo Training Ground | 11 |
| Fire Temple | 34 | Ganon's Castle | 27 |
| Water Temple | 26 | | |

So the layouts are the normal dungeons' rooms with different contents, as in the original Master Quest. 1.0.0
had a one-room placeholder for each. Each record holds a progress step and a "room cleared" flag; they look like
the per-room progress behind Navi's dungeon hints (inferred).

## What the event names give away

*Data.* 1.1.1 adds 88 "this event has played" flags, all of them Master Quest events. The game stores only a
hash of each name. 83 names were recovered by guessing from the game's own naming scheme
(`<Dungeon>_MQ_<Room>_<Thing><number>`). Each one matches two independent hashes and falls in the right place in
the alphabetically sorted list, so none is a chance match.

| Dungeon | Named | Recovered events |
| --- | ---: | --- |
| Fire Temple | 24 of 24 | 20 switches, in rooms 01, 04 (two), 05, 07, 08 (two), 10, 11 (two), 13 (two), 14, 15, 16 (four), 18 and 24; two torch switches in room 01; a shutter in room 02; a second meeting with Darunia |
| Jabu-Jabu | 27 of 27 | "all enemies defeated" in rooms 09, 12, 13 and 14; cow switches in rooms 00, 01 (three), 02 (two), 03, 04, 05, 06 and 17 (three); step switches in rooms 03 and 07; a spider web in room 07; a "hit switch" event; two cows, each with "give milk" and "put milk in a bottle" events |
| Water Temple | 21 of 21 | "Longshot obtained" in room 17; "all candles lit" in room 01; "hook appeared" in rooms 05 (two) and 18; a first switch in rooms 00, 04, 08, 10 and 20; switches in rooms 11 and 12; candle fires in rooms 03, 08 and 15; a chest appearing in room 16; rooms 02 and 14 cleared; a shutter in room 00; water-level and camera events in rooms 06 and 17 |
| Deku Tree | 8 of 8 | a falling ladder in room C; a candle fire and a water-level drop in room G; switches in rooms B and F; a chest appearing in room D; rooms B and H cleared |
| Spirit Temple | 3 of 8 | ocarina events in rooms 08, 15 and 29 |

What this suggests (inferred):

- **Jabu-Jabu** is built around the cows in the walls as switches, as in the original Master Quest: thirteen cow
  switches over eight rooms, and the cows can be milked.
- **The Fire Temple** is the most switch-heavy: 22 switch events over thirteen rooms.
- **The Water Temple** still gives the Longshot, and adds hookshot targets that appear when something is done.
- Two more Deku Tree events (a candle and spider web, a candle stick in room D) were already listed in 1.0.0.

Five names are still unknown, all in the Spirit Temple; they are known only by their position in the sorted
list. The other seven dungeons have no event flags yet, only room records.

## Other traces

- **About a thousand new per-object save flags** (1,029) belong to objects that are not in the shipped maps. By
  location: Jabu-Jabu 159, Kakariko 40, Zora's Fountain 28, Deku Tree 18, Ganon's Castle 10, Zora's Domain 9.
  Their keys are object ids, not names, so nothing more can be read from them (data).
- **A cow switch for Jabu-Jabu** exists in the code as a parameter class, the only Master Quest object named in
  the executable (code).
- **Light rigs** for four `_MQ` actors are in the graphics settings (data).
- **A layout animation per dungeon and the nickname screen** have Master Quest frame offsets (code).

## What is not known

- Anything about enemy, item or puzzle placement beyond the event names above.
- Five of the 88 event names (Spirit Temple).
- What the mode-select screen is, when the add-on is released, and what it costs.
- Whether item locations or rewards differ.
