"""Frame time over the scripted Kokiri Forest walk, without and with the shared JIT code cache.

usage: uv run --with matplotlib --with numpy --with pillow python walk_frame_times.py \
           RUN_WITHOUT RUN_WITH OUT.png
       RUN_* are harness run folders (tools/harness/runs/ab-<date>-<time>/<label>/) holding frames.bin and result.json.

frames.bin is one little-endian uint64 timestamp (ns) per presented frame; result.json's "marks" give the frame index
where each phase starts. The walk is frames marks["walk"] .. marks["stand2"] (as in tools/diag/frames.py).
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, NullLocator

import style as S


def walk(run):
    rd = Path(run)
    res = json.loads((rd / "result.json").read_text())
    ts = np.fromfile(rd / "frames.bin", dtype="<u8")
    a, b = res["marks"]["walk"], res["marks"]["stand2"]
    seg = ts[a:b + 1].astype(np.int64)
    ft = np.diff(seg) / 1e6
    t = (seg[1:] - seg[0]) / 1e9
    return t, ft, res


def main(run_without, run_with, out):
    S.setup()
    fig, axes = plt.subplots(2, 1, figsize=(S.WIDTH_IN, 6.6), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.085, right=0.975, top=0.84, bottom=0.15, hspace=0.30)
    runs = [(run_without, "Without the shared JIT code cache (installed build before the port)", S.GREY),
            (run_with, "With the shared JIT code cache, 512 MiB (the change in the pinned build)", S.BLUE)]
    for ax, (run, name, col) in zip(axes, runs):
        t, ft, res = walk(run)
        # each frame drawn over its own duration: frame i spans (t[i-1], t[i]]
        ax.step(np.r_[0.0, t], np.r_[ft[0], ft], where="pre", color=S.TEXT2 if col == S.GREY else col,
                linewidth=0.9)
        med, mx = np.median(ft), ft.max()
        p95 = np.sort(ft)[min(len(ft) - 1, int(0.95 * len(ft)))]
        ax.axhline(16.7, color=S.LINE60, linewidth=1.0, linestyle=(0, (4, 2.5)))
        ax.set_yscale("log")
        ax.set_ylim(12, 1000)
        ax.yaxis.set_major_locator(FixedLocator([15, 20, 30, 50, 100, 300, 1000]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.set_yticklabels(["15", "20", "30", "50", "100", "300", "1000"])
        ax.grid(axis="x", visible=False)
        i = int(ft.argmax())
        ax.annotate(f"worst frame {mx:.0f} ms", xy=(t[i], mx), xytext=(8, -2), textcoords="offset points",
                    fontsize=8.4, color=S.TEXT, va="center")
        ax.set_title(name, loc="left", fontsize=9.6, color=S.TEXT, pad=4)
        lab = Path(run).parent.name + " / " + Path(run).name
        ax.text(0.995, 0.95, f"median {med:.1f} ms · p95 {p95:.1f} ms · {len(ft)} frames\nrun {lab}",
                transform=ax.transAxes, ha="right", va="top", fontsize=7.8, color=S.TEXT2, linespacing=1.4)
        ax.set_ylabel("Frame time (ms, log)")
    for ax in axes:
        ax.text(0.995, 16.7, "16.7 ms = 60 fps", transform=ax.get_yaxis_transform(), color=S.LINE60,
                fontsize=7.8, ha="right", va="top")
    axes[1].set_xlabel("Time since the walk started (s)")
    S.titles(fig, "Frame time over the scripted Kokiri Forest walk, without and with the shared JIT cache",
             S.CONDITIONS + ". Walk with turns from the spawn, ~310 frames.", y=0.98)
    fig.text(0.012, 0.05,
             "Without the shared cache a core's 128 MiB code cache fills, is flushed whole and recompiled: "
             "one frame of 312–645 ms in 3 of 3 runs of this batch.\n"
             "With it, 0 of 3 runs hitched (worst frames 51–60 ms). One representative run of each is drawn; "
             "frames.bin per-frame timestamps, local run data.",
             fontsize=7.6, color=S.TEXT2, va="top")
    fig.savefig(out, dpi=S.DPI)


if __name__ == "__main__":
    main(*sys.argv[1:4])
