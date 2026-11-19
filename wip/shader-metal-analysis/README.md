# 2026-11-17: OOT-remake shader Metal compilation analysis

The game's Nvidia shaders compared with their Metal translations, offline. The session and its 2 sub-sessions
(texture latency, argument-buffer cost) are archived.

| Folder | What it holds |
| --- | --- |
| [guest-vs-metal-shaders/](guest-vs-metal-shaders/README.md) | The write-up. The translation is faithful and bit-exact; a third of automatic-mip samples get the wrong mip on Apple (fix prototyped, not checked in game); what the translation costs |
| [shader-compare/](shader-compare/README.md) | The tools and probes behind it |

Open: check the mip-level fix in the running game.
