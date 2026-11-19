"""Frame time standing at the Kokiri Forest spawn, one bar per step, from stock build 228 to the pinned build.

usage: uv run --with matplotlib --with numpy --with pillow python frame_time_steps.py DATA.csv OUT.png
       (DATA.csv is media/data/frame-time-steps.csv)

Two harnesses measured these steps (TRACKER.md, "How to read the numbers"); their figures for the same build differ by
1-2 ms, so the two groups are drawn as separate blocks and not joined. In the second block each step was measured as
an A/B in its own batch: the hollow marker is that batch's figure without the step.
"""
import csv
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import style as S

FILL = {"baseline": S.GREY, "upstream": S.ORANGE, "ours": S.BLUE, "both": S.ORANGE}
HATCH = {"both": "////"}


def num(s):
    return float(s) if s.strip() else None


def main(data, out):
    rows = list(csv.DictReader(open(data)))
    S.setup()
    fig = plt.figure(figsize=(S.WIDTH_IN, 6.3))
    ax = fig.add_axes([0.335, 0.175, 0.625, 0.62])

    groups = [
        ("V", "Harness V (tools/verify), 2026-11-16: median of 1,050 standing frames"),
        ("H", "Harness H (tools/harness), 2026-11-17/18: standing p50, each step an A/B in its own batch"),
    ]
    y = 0
    yticks, ylabels, headers = [], [], []
    for key, header in groups:
        headers.append((y, header))
        y += 1
        for r in [r for r in rows if r["panel"] == key]:
            lo, hi = num(r["lo_ms"]), num(r["hi_ms"])
            mid = (lo + hi) / 2
            w = r["whose"]
            ax.barh(y, mid, height=0.62, color=FILL[w], hatch=HATCH.get(w), edgecolor="white" if w == "both" else FILL[w],
                    linewidth=0)
            if w == "both":  # orange face with blue hatch: other people's PRs and changes made here
                ax.barh(y, mid, height=0.62, color="none", hatch="////", edgecolor=S.BLUE, linewidth=0)
            if hi > lo:
                ax.errorbar(mid, y, xerr=[[mid - lo], [hi - mid]], fmt="none", ecolor=S.TEXT, elinewidth=0.9,
                            capsize=3, capthick=0.9)
            txt = f"{lo:.1f}" if hi == lo else f"{lo:.1f}–{hi:.1f}"
            bl, bh = num(r["before_lo_ms"]), num(r["before_hi_ms"])
            xr = max(hi, bh or 0)
            if bl is not None:
                bmid = (bl + bh) / 2
                ax.plot([bmid], [y], marker="D", markersize=6, markerfacecolor=S.SURFACE, markeredgecolor=S.TEXT2,
                        markeredgewidth=1.1, linestyle="none", zorder=5)
                txt += f" ms  (without: {bl:.1f}" + ("" if bh == bl else f"–{bh:.1f}") + ")"
            else:
                txt += " ms"
            ax.text(xr + 1.1, y, txt, va="center", ha="left", fontsize=8.4, color=S.TEXT)
            yticks.append(y)
            ylabels.append(r["label"])
            y += 1
        y += 0.35

    for hy, htxt in headers:
        ax.text(-0.5, hy + 0.1, htxt, transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.6,
                weight="bold", color=S.TEXT2, zorder=6,
                bbox=dict(boxstyle="square,pad=0.15", facecolor=S.SURFACE, edgecolor="none"))
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8.8, color=S.TEXT)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(y - 0.6, -0.6)
    ax.set_xlim(0, 50)
    ax.set_xticks(range(0, 51, 10))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Frame time standing at the spawn (ms, median; lower is faster)")
    ax.spines["left"].set_visible(False)

    ax.axvline(16.7, color=S.LINE60, linewidth=1.1, linestyle=(0, (4, 2.5)), zorder=4)
    ax.text(16.7, -0.7, "16.7 ms = 60 fps", color=S.LINE60, fontsize=8.2, va="bottom", ha="center", clip_on=False)

    S.titles(fig, "Standing frame time, stock Lichii build 228 to the pinned build",
             S.CONDITIONS + ". Steps in the order they went in. No step reaches 16.7 ms.")

    handles = [Patch(facecolor=S.GREY, label="stock release"),
               Patch(facecolor=S.ORANGE, label="other people's upstream pull requests"),
               Patch(facecolor=S.BLUE, label="changes made in this repository"),
               Patch(facecolor=S.ORANGE, hatch="////", edgecolor=S.BLUE, label="both"),
               Line2D([], [], color=S.TEXT, marker="|", markersize=8, linestyle="-", linewidth=0.9,
                      label="measured range (bar at midpoint)"),
               Line2D([], [], marker="D", markersize=6, markerfacecolor=S.SURFACE, markeredgecolor=S.TEXT2,
                      linestyle="none", label="without the step (same batch)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.005, 0.895), ncol=3, fontsize=8.2,
               handlelength=1.6, columnspacing=1.4)
    fig.text(0.012, 0.062,
             "The two harnesses give 1–2 ms different figures for the same build, so the two blocks are not one series. "
             "The diamond is the same batch\nwithout the step. The last step's figures are the standing phase after the walk "
             "(stand2). Sources per bar: media/data/frame-time-steps.csv.",
             fontsize=7.6, color=S.TEXT2, va="top")
    fig.savefig(out, dpi=S.DPI)


if __name__ == "__main__":
    main(*sys.argv[1:3])
