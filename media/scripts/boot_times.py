"""Boot time without and with MoltenVK PR #2901 (compile pipeline-cache shader libraries when first used).

usage: uv run --with matplotlib --with numpy --with pillow python boot_times.py DATA.csv OUT.png
       (DATA.csv is media/data/boot-times.csv)
"""
import csv
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import style as S


def main(data, out):
    rows = list(csv.DictReader(open(data)))
    cases = list(dict.fromkeys(r["case"] for r in rows))
    S.setup()
    fig = plt.figure(figsize=(S.WIDTH_IN, 4.1))
    ax = fig.add_axes([0.30, 0.20, 0.66, 0.55])
    y, ticks = 0, []
    for case in cases:
        for k, r in enumerate([r for r in rows if r["case"] == case]):
            lo, hi = float(r["lo_s"]), float(r["hi_s"])
            mid = (lo + hi) / 2
            with_ = r["variant"].startswith("with ")
            yy = y + k * 0.42
            ax.barh(yy, mid, height=0.36, color=S.BLUE if with_ else S.GREY, linewidth=0)
            if hi > lo:
                ax.errorbar(mid, yy, xerr=[[mid - lo], [hi - mid]], fmt="none", ecolor=S.TEXT, elinewidth=0.9,
                            capsize=3, capthick=0.9)
                txt = f"{lo:g}–{hi:g} s"
            else:
                txt = f"{lo:g} s"
            ax.text(hi + 8, yy, txt, va="center", ha="left", fontsize=8.6, color=S.TEXT)
        ticks.append(y + 0.21)
        y += 1.25
    ax.set_yticks(ticks)
    ax.set_yticklabels(["Cold boot\n(empty Metal shader cache)", "First boot of a new MoltenVK\nlibrary on a filled cache"],
                       fontsize=8.8, color=S.TEXT)
    ax.tick_params(axis="y", length=0)
    ax.invert_yaxis()
    ax.set_xlim(0, 540)
    ax.set_xlabel("Time from launch to the end of boot (s; lower is faster)")
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    S.titles(fig, "Boot time without and with MoltenVK PR #2901",
             S.CONDITIONS + ". #2901 compiles each cached shader library when first used.", y=0.975)
    fig.legend(handles=[Patch(color=S.GREY, label="without #2901 (every library compiled at boot, one at a time)"),
                        Patch(color=S.BLUE, label="with #2901")],
               loc="upper left", bbox_to_anchor=(0.005, 0.87), ncol=2, fontsize=8.2, handlelength=1.4)
    fig.text(0.012, 0.075,
             "Cold boot with #2901: 97.4–100.7 s in the pinned build (bar at midpoint); a separate #2901 test build "
             "measured 78.8 s, not looked into.\nSource: research/emulator-options/README.md, "
             "\"Parallel shader compiles at boot\".",
             fontsize=7.6, color=S.TEXT2, va="top")
    fig.savefig(out, dpi=S.DPI)


if __name__ == "__main__":
    main(*sys.argv[1:3])
