#!/usr/bin/env python3
"""persist.py BURST_DIR...: for a burst of screenshots taken while Link stands still, in how many frames is each
pixel clipped white?

The same pixels white in every frame means a fixed cause (wrong instance, position arithmetic). Pixels that come
and go from frame to frame mean data that changes: uninitialised memory, ordering between GPU steps. Writes
BURST_DIR/persist.png (black = never white, dark red = sometimes, white = in every frame) and prints the split.
Uses whitecount's level and HUD mask."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import whitecount  # noqa: E402


def mask(h, w):
    keep = np.ones((h, w), bool)
    keep[: int(0.05 * h)] = False; keep[int(0.96 * h):] = False
    keep[: int(0.16 * h), : int(0.12 * w)] = False
    keep[: int(0.27 * h), int(0.86 * w):] = False
    keep[int(0.64 * h):, : int(0.24 * w)] = False
    keep[int(0.72 * h):, int(0.74 * w):] = False
    return keep


def persistence(d):
    files = sorted(Path(d).glob("f*.png"))
    stack = np.stack([(np.asarray(Image.open(f).convert("RGB")) >= whitecount.LEVEL).all(axis=2) for f in files])
    n = len(files); keep = mask(*stack.shape[1:])
    count = stack.sum(axis=0) * keep
    ever = count > 0
    # frames with (almost) no white at all are the clean ones; leave them out of "every frame"
    per_frame = (stack & keep).sum(axis=(1, 2)); affected = per_frame > whitecount.THRESHOLD * keep.sum()
    na = int(affected.sum())
    count_a = (stack[affected] & keep).sum(axis=0) if na else count * 0
    out = {"frames": n, "affected_frames": na, "ever_white_px": int(ever.sum()),
           "always_px": int((count_a == na).sum()) if na else 0,
           "over_90pct_px": int((count_a >= 0.9 * na).sum()) if na else 0,
           "under_50pct_px": int(((count_a > 0) & (count_a < 0.5 * na)).sum()) if na else 0}
    if out["ever_white_px"]:
        for k in ("always_px", "over_90pct_px", "under_50pct_px"):
            out[k.replace("_px", "_share")] = round(out[k] / out["ever_white_px"], 3)
    img = np.zeros(count.shape + (3,), np.uint8)
    if na:
        frac = count_a / na
        img[..., 0] = (80 + 175 * frac) * (count_a > 0)
        img[frac >= 0.999] = 255
    Image.fromarray(img).save(Path(d) / "persist.png")
    return out


def picture_metrics(path):
    """Two rough signs of a corrupted picture in one screenshot, as shares of the scene outside the HUD:
    clipped_pct (R, G and B all >= 235: a blown-out frame is over 15 %, a normal Kokiri one under 5 %) and
    vivid_pct (bright, strongly saturated pixels: rainbow shards are over 0.15 %, a normal frame under 0.1 %).
    Thresholds come from the two corrupted Hypervisor boots of 2026-11-18 and ~120 clean runs."""
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    keep = mask(*a.shape[:2]); mx = a.max(axis=2); mn = a.min(axis=2)
    clipped = ((a >= 235).all(axis=2) & keep).sum() / keep.sum() * 100
    vivid = ((mx > 170) & (mx - mn > 140) & keep).sum() / keep.sum() * 100
    return {"clipped_pct": round(float(clipped), 2), "vivid_pct": round(float(vivid), 3),
            "corrupt": bool(clipped > 15 or vivid > 0.15)}


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(arg, persistence(arg))
