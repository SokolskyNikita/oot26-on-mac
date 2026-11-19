"""Side-by-side before/after picture with labels burned in.

usage: uv run --with matplotlib --with numpy --with pillow python pair.py BEFORE AFTER OUT \
           --title T --before-label B --after-label A [--note N] [--gif-frames K]

BEFORE / AFTER are window captures (PNG, JPG, or GIF bursts when OUT ends in .gif). The macOS title bar and Lichii's
status bar are cropped off: the game area is the 16:9 block that ends 27/1280 of the width above the bottom edge.
That also removes the status bar's fps readout, which is not a measurement.
"""
import argparse
from pathlib import Path

import matplotlib.font_manager
from PIL import Image, ImageDraw, ImageFont, ImageSequence

FONT = matplotlib.font_manager.findfont("DejaVu Sans")
FONT_B = matplotlib.font_manager.findfont(matplotlib.font_manager.FontProperties(family="DejaVu Sans", weight="bold"))
SURFACE = (252, 252, 251)
TEXT = (11, 11, 11)
TEXT2 = (82, 81, 78)
BEFORE_C = (138, 137, 132)
AFTER_C = (42, 120, 214)


def game_area(im):
    w, h = im.size
    gh = round(w * 9 / 16)
    sb = round(27 * w / 1280)
    top = max(0, h - sb - gh)
    return im.crop((0, top, w, top + gh))


def wrap(draw, text, font, width):
    out, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if draw.textlength(t, font=font) <= width:
            line = t
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def compose(before, after, a, W=1800, M=24, G=24):
    k_ = W / 1800  # text and spacing scale with the output width
    z = lambda v: max(1, round(v * k_))
    pw = (W - 2 * M - G) // 2
    ph = round(pw * 9 / 16)
    f_t = ImageFont.truetype(FONT_B, z(34))
    f_s = ImageFont.truetype(FONT, z(22))
    f_l = ImageFont.truetype(FONT_B, z(26))
    f_d = ImageFont.truetype(FONT, z(22))
    scratch = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    note = wrap(scratch, a.note, f_s, W - 2 * M) if a.note else []
    bl = wrap(scratch, a.before_label, f_d, pw)
    al = wrap(scratch, a.after_label, f_d, pw)
    nl = max(len(bl), len(al))
    y_title = M
    y_lab = y_title + z(52)
    y_img = y_lab + z(36) + nl * z(28) + z(10)
    H = y_img + ph + (z(16) + z(28) * len(note) if note else 0) + M
    im = Image.new("RGB", (W, H), SURFACE)
    d = ImageDraw.Draw(im)
    d.text((M, y_title), a.title, font=f_t, fill=TEXT)
    for x, word, col, lines, src in ((M, "before", BEFORE_C, bl, before), (M + pw + G, "after", AFTER_C, al, after)):
        d.rectangle((x, y_lab + z(6), x + z(18), y_lab + z(24)), fill=col)
        d.text((x + z(28), y_lab), word, font=f_l, fill=TEXT)
        for k, ln in enumerate(lines):
            d.text((x, y_lab + z(36) + k * z(28)), ln, font=f_d, fill=TEXT2)
        im.paste(game_area(src.convert("RGB")).resize((pw, ph), Image.LANCZOS), (x, y_img))
    for k, ln in enumerate(note):
        d.text((M, y_img + ph + z(16) + k * z(28)), ln, font=f_s, fill=TEXT2)
    return im


def main():
    p = argparse.ArgumentParser()
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("out")
    p.add_argument("--title", required=True)
    p.add_argument("--before-label", required=True)
    p.add_argument("--after-label", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--frame", type=int, default=0, help="frame of a GIF input to use for a PNG output")
    p.add_argument("--gif-frames", type=int, default=8)
    p.add_argument("--gif-width", type=int, default=1000)
    a = p.parse_args()
    if a.out.endswith(".gif"):
        def frames_of(src):
            # a burst folder of full-resolution frames (f000.png, f001.png, ...) or a GIF
            if Path(src).is_dir():
                return [Image.open(f).convert("RGB") for f in sorted(Path(src).glob("f[0-9][0-9][0-9].png"))]
            return [f.convert("RGB") for f in ImageSequence.Iterator(Image.open(src))]
        fb = frames_of(a.before)[:a.gif_frames]
        fa = frames_of(a.after)[:a.gif_frames]
        n = min(len(fb), len(fa))
        rgb = [compose(fb[i], fa[i], a, W=a.gif_width, M=14, G=14) for i in range(n)]
        # one palette for all frames, built from every frame side by side
        w, h = rgb[0].size
        sheet = Image.new("RGB", (w, h * n))
        for i, c in enumerate(rgb):
            sheet.paste(c, (0, h * i))
        pal = sheet.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        frames = [c.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for c in rgb]
        frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=350, loop=0, optimize=True)
    else:
        def load(path):
            im = Image.open(path)
            if getattr(im, "n_frames", 1) > 1:
                im.seek(a.frame)
            return im.copy()
        compose(load(a.before), load(a.after), a).save(a.out, optimize=True)


if __name__ == "__main__":
    main()
