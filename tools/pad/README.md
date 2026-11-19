# pad: a virtual controller for Lichii

A DSU ("cemuhook") controller server and its command-line client, so a script can press buttons in Lichii with no
window focus. Only [`../verify/verify.py run`](../verify/README.md) uses it, and it starts `dsu_server.py` itself when
nothing answers on the control port, then stops it when the run ends. The harness (`../harness/ab.py`) does not use
it: it sends input through Lichii's debug server.

| File | What |
| --- | --- |
| `dsu_server.py` | `python3 dsu_server.py` (runs until killed): reports one pad to Lichii on UDP `127.0.0.1:26760`; its buttons and sticks are whatever was last set on the control socket, UDP `127.0.0.1:26761` (`press NAME…`, `release NAME…`, `stick ls|rs X Y`, `reset`, `state`) |
| `pad.py` | `python3 pad.py tap:a walk:0,1:2 chord:r+rdown …`: steps sent to the server (the full list is in its docstring) |

## Binding player 1 to it in Lichii (once)

With Lichii closed, these lines in `~/.config/lichii/qt-config.ini`, `[Controls]` section (each `KEY\default=false`
beside it), or the same through Lichii's controller settings:

- `enable_udp_controller=true` and `udp_input_servers=127.0.0.1:26760` (the DSU client and the server it polls);
- `player_0_connected=true`, `player_0_type=0` (Pro Controller);
- player 1's buttons and sticks mapped to that pad: `player_0_button_a="engine:cemuhookudp,guid:0000000000000000000000007f000001,port:26760,pad:0,button:8192"`,
  and the same for the others with the DSU button bits (`button:` values: b 16384, x 4096, y 32768, l 1024, r 2048,
  zl 256, zr 512, plus 8, minus 1, lstick 2, rstick 4, dup 16, dright 32, ddown 64, dleft 128), and
  `player_0_lstick="engine:cemuhookudp,guid:0000000000000000000000007f000001,port:26760,pad:0,axis_x:0,axis_y:1"`,
  `player_0_rstick="…,axis_x:2,axis_y:3"`.

Lichii's own controller dialog writes the same lines when you pick the "CemuhookUDP" device for player 1 while the
server runs. Then run `python3 ../harness/ab.py --make-master --force` so the harness's master config has them too.
