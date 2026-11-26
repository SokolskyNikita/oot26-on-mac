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

- **One setting per account.** It is stored in the account's save file, so it applies to every save slot of
  that user.
- **The world is mirrored.** With the setting on, the game flips the stick, the camera input and Link's
  movement, sets a graphics flag and swaps the left and right audio channels (the audio part is inferred).
- **Separate saves.** The setting selects a second set of save slots, so Master Quest files do not overwrite
  normal ones.
- **Separate dungeon maps.** A scene change appends `_MQ` to the scene name, so each Master Quest dungeon is a
  separate map.
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
1.1.1 clears the value at boot when the add-on is not owned. It is not known whether that check always finishes
before the mode is first applied.

## Which places get a Master Quest version

*Code and data.* Thirteen scene names get the `_MQ` suffix:

- **Child dungeons:** Inside the Deku Tree, Dodongo's Cavern, Inside Jabu-Jabu's Belly.
- **Temples:** Forest, Fire, Water, Shadow and Spirit.
- **Smaller dungeons:** Bottom of the Well, Ice Cavern, Gerudo Training Ground.
- **Ganon's Castle:** Inside Ganon's Castle and Collapsing Ganon's Castle.

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

*Data; the readings are inferred.* The game keeps a flag for each scripted moment it should show only once: the
camera cutting to a door that opens, a chest appearing, a short cutscene. 1.1.1 adds 88 of these flags, all for
Master Quest dungeons. Only a hash of each name is stored. 83 of the names were recovered by guessing from the
game's naming scheme and checking each guess against two hashes and the list's alphabetical order.

Because every flag is one scripted moment in one room, the names are a partial list of what happens where. Five
dungeons have them so far.

### Inside Jabu-Jabu's Belly (27 flags, all named)

| Flag names | What they are |
| --- | --- |
| `InsideJabuJabuBelly_MQ_Room_00_CowSwitch`, the same for rooms 03, 04, 05, 06 and 17, `Room_01_CowSwitch1` to `3`, `Room_02_CowSwitch1` and `2`, `Room_17_CowSwitch2` and `3` | thirteen cow switches in eight rooms |
| `Animal_Cow_MQ_InsideJabuJabuBelly_GiveMilk`, `…_PushToBottleMilk`, `…_D_T` and the same three with `_Switch` | the cow's usual events (it gives milk, the milk goes in a bottle, a talk), once for a plain cow and once for a cow that is a switch |
| `InsideJabuJabuBelly_MQ_Room_09_DefeatAllEnemy`, the same for rooms 12, 13 and 14 | four rooms that react when every enemy is dead |
| `…_Room_03_StepSwitch`, `…_Room_07_StepSwitch`, `…_Room_07_SpiderNet`, `…_MQ_HitSwitch` | two floor switches, a spider web, a switch that is hit |

The original Master Quest filled this dungeon with cows set into the walls that work as switches when shot. The
remake keeps that: cow switches are the largest group of flags in any dungeon. The milk events say these cows
are real cow actors, so Link can play Epona's Song to them and fill a bottle inside Jabu-Jabu.

### Fire Temple (24 flags, all named)

| Flag names | What they are |
| --- | --- |
| `FireTemple_MQ_Room01_Switch02`, `Room04_Switch00` and `01`, `Room05_Switch00` and so on through rooms 07, 08, 10, 11, 13, 14, 15, 16 (`Switch00` to `03`), 18 and 24 | twenty switches in thirteen rooms |
| `FireTemple_MQ_Room01_TorchSwitch00` and `01` | two switches in room 01 that are torches |
| `FireTemple_MQ_OpenShutter_Room02` | a barred door opening in room 02 |
| `Demo_FireTemple_MQ_MeetAgainDarniaEvent` | the meeting with Darunia inside the temple, which the normal game also has |

Each switch has its own flag here. The normal Fire Temple's flags are mostly named after what the camera shows
(`FireTemple_SwitchFireCamera_Room04`). Twenty-two numbered switches read like a dungeon rebuilt around
switches, with room 16 (four of them) as the busiest room, and two of the switches in room 01 are torches to
light.

### Water Temple (21 flags, all named)

| Flag names | What they are |
| --- | --- |
| `WaterTemple_MQ_Room17_LongHookGet` | Link gets the Longshot in room 17 |
| `WaterTemple_MQ_Room18_HookAppeared`, `Room05_HookAppeared_01` and `_02` | hookshot targets that appear, one in room 18 and two in room 05 |
| `WaterTemple_MQ_Room01_AllCandleFire`, `Room03_CandleFire`, `Room08_CandleFire`, `Room15_CandleFire` | torches lit in four rooms; in room 01 all of them must be lit |
| `Room00_FirstSwitch01`, the same for rooms 04, 08, 10 and 20; `Room11_Switch01`, `Room12_Switch01` | switches in seven rooms |
| `Room02_Cleared`, `Room14_Cleared`, `Room16_TBoxAppeared`, `Gimmick_OpenShutter_Room00` | two rooms cleared of enemies, a chest appearing, a barred door opening |
| `Room06_Waterlevelrise_FocusOnGimmick`, `Room17_FocusOnGimmick` | camera cuts when the water rises in room 06 and to a mechanism in room 17 |

The Longshot is still this dungeon's item, in room 17. In the normal dungeon the flag near it is
`WaterTemple_Room07_LongHook_FocusOnGimmick`, so the item's room number changed. Hookshot targets
appear on cue in two rooms. Four rooms have torches to light, in a temple full of water, as the original Master
Quest Water Temple did; no normal dungeon in this game has a `CandleFire` flag.

### Inside the Deku Tree (8 new flags, all named, plus 2 older ones)

| Flag names | What they are |
| --- | --- |
| `InsideTheDekuTree_MQ_RoomC_FallingLadder` | a ladder that falls in room C |
| `InsideTheDekuTree_MQ_Gimmick_RoomG_WaterLevelDrop`, `RoomG_CandleFire` | the water draining in room G and a torch lit there |
| `RoomB_Switch01`, `RoomF_Switch01`, `RoomD_TreasureBoxAppeared` | two switches and a chest that appears |
| `RoomB_Cleared`, `RoomH_Cleared` | two rooms cleared of enemies |
| `InsideTheDekuTree_MQ_Gimmick_CandleAndSpiderWeb_01`, `Gimmick_RoomD_CandleStick` (both already in 1.0.0) | burning a web with a lit stick and a torch stand in room D |

These follow the normal dungeon closely. It has `InsideTheDekuTree_Gimmick_FallingLadder` and
`Gimmick_RoomG_WaterLevelDrop` too, so the falling ladder and the draining basement survive, with the puzzles
around them changed. The two flags from 1.0.0 suggest the Deku Tree was the first Master Quest dungeon worked on.

### Spirit Temple (8 flags, 3 named)

`SpiritTemple_MQ_Level_Room_08_Ocarina`, `Room_15` and `Room_29`: three rooms where a song has to be played. The
normal game uses the same name pattern for its song spots (`BottomOfTheWell_Level_Room_01_Ocarina`). The other
five names did not come out, so they probably use words the rest of the game's flags do not.

### The other eight dungeons

Dodongo's Cavern, the Forest and Shadow Temples, the Bottom of the Well, the Ice Cavern, the Gerudo Training
Ground and both Ganon's Castle scenes have no event flags yet. The five dungeons above are the ones whose
scripting had started by 1.1.1.

## Other traces

- **About a thousand new per-object save flags** (1,029) belong to objects that are not in the shipped maps. By
  location: Jabu-Jabu 159, Kakariko 40, Zora's Fountain 28, Deku Tree 18, Ganon's Castle 10, Zora's Domain 9.
  Their keys are object ids, which carry no name, so nothing more can be read from them (data).
- **A cow switch for Jabu-Jabu** exists in the code as a parameter class, the only Master Quest object named in
  the executable (code).
- **Light rigs** for four `_MQ` actors are in the graphics settings (data).
- **A layout animation per dungeon and the nickname screen** have Master Quest frame offsets (code).

## What is not known

- What the mode-select screen is, when the add-on is released and what it costs.
- Whether item locations or rewards differ.
- Enemy and puzzle placement in the eight dungeons that have no event flags yet.
