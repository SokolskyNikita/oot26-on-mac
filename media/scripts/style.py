"""Shared look for the media charts: near-white background, dark text, thin recessive axes.

Pictures are drawn for a 900-px-wide layout at 2x (1800 px): 9 in wide at 200 dpi.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e4e3df"
BLUE = "#2a78d6"     # changes made in this repository / with the change
ORANGE = "#eb6834"   # other people's upstream pull requests
GREY = "#a9a8a3"     # baseline / without the change
LINE60 = "#c0392b"   # the 16.7 ms (60 fps) budget line

WIDTH_IN = 9.0
DPI = 200

CONDITIONS = "Apple M4 Pro, macOS 27.0.1, Kokiri Forest, 1x resolution, handheld"


def setup():
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "text.color": TEXT,
        "axes.labelcolor": TEXT2,
        "axes.edgecolor": MUTED,
        "axes.linewidth": 0.6,
        "xtick.color": TEXT2,
        "ytick.color": TEXT2,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
    })


def titles(fig, title, subtitle, y=0.985):
    fig.text(0.012, y, title, ha="left", va="top", fontsize=12.5, weight="bold", color=TEXT)
    fig.text(0.012, y - 0.052, subtitle, ha="left", va="top", fontsize=8.6, color=TEXT2)
