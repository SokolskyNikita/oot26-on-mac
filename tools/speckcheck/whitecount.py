#!/usr/bin/env python3
"""whitecount.py PNG_OR_DIR...: share of clipped-white pixels in each screenshot's scene area.

The flashing at the Kokiri cave wall shows as pure-white specks on foliage. This counts pixels with R, G and B all
>= 235, leaving out the HUD corners (hearts, item, watches box, minimap) and the title and status bars, so a frame
with the specks stands out without comparing neighbouring frames. For a folder it prints one line per PNG and the
number of frames over the threshold (0.3 % of the scene)."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

LEVEL = 235
THRESHOLD = 0.003


def share(path):
    a = np.asarray(Image.open(path).convert("RGB"))
    h, w, _ = a.shape
    keep = np.ones((h, w), bool)
    keep[: int(0.05 * h)] = False; keep[int(0.96 * h):] = False          # title bar, status bar
    keep[: int(0.16 * h), : int(0.12 * w)] = False                          # hearts
    keep[: int(0.27 * h), int(0.86 * w):] = False                           # item
    keep[int(0.64 * h):, : int(0.24 * w)] = False                           # watches box
    keep[int(0.72 * h):, int(0.74 * w):] = False                            # minimap
    white = (a >= LEVEL).all(axis=2) & keep
    return white.sum() / keep.sum()


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        files = sorted(p.glob("*.png")) if p.is_dir() else [p]
        vals = [(f, share(f)) for f in files]
        for f, v in vals:
            print(f"{v * 100:6.3f} %  {'SPECKS' if v > THRESHOLD else '      '}  {f}")
        if p.is_dir() and vals:
            n = sum(v > THRESHOLD for _, v in vals)
            print(f"{p}: {n} of {len(vals)} frames over {THRESHOLD * 100:.1f} %, max {max(v for _, v in vals) * 100:.3f} %")
