"""Steps a harness run does once Link stands at the end of its walk (spec key "at_end", see speck_run.sh).

Before the steps it reads Link's position from memory (the harness's own reader) every 10 frames until he has
stood still for 20, and stores where that is and how far from the cave wall spot (result.json: at_end.stand).

Each step is one of:
  {"burst": N, "name": "before"}             N screenshots in a row into <run>/<name>/, with the clipped-white share
                                             of each (whitecount.share); summary in result.json under at_end, plus
                                             <name>/sheet.png (every frame, small) and <name>/burst.gif as a record.
                                             "via": "window" (default) takes them from the window through the verify
                                             hook, which is what is on screen; "via": "server" uses the debug
                                             server's screenshot, which makes the emulator render that frame in step
                                             and so shows a clean frame now and then (seen 2026-11-17: 1-6 of 30).
  {"call": METHOD, "params": {...}, "save": "name"}   one debug-server call; its result goes to <run>/<name>.json
  {"frames": N}                              wait N presented frames
  {"watch_written": PROGRAM, "reads": N, "every_frames": F, "words": W, "name": "watch"}
                                             after a capture_frame with buffers: the storage buffers that program
                                             writes, read from GPU memory N times, F frames apart (first W words)
  {"reject_each": [[hash, ...], ...], "burst": N}     for each group: reject those shader hashes, burst, restore
"""
import json
import shutil
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import whitecount  # noqa: E402


HOOK_PORT = 26799  # the verify hook's port, as in ab.py


def hook(cmd):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sock.settimeout(5)
    sock.sendto(cmd.encode(), ("127.0.0.1", HOOK_PORT))
    try:
        return sock.recvfrom(4096)[0].decode()
    except socket.timeout:
        return ""


def record(d, files):
    """sheet.png (all frames, 240 px wide each) and burst.gif (480 px wide, 5 frames a second) in d."""
    from PIL import Image
    ims = [Image.open(f).convert("RGB") for f in files]
    w, h = ims[0].size; tw = 240; th = max(1, h * tw // w); cols = 6
    sheet = Image.new("RGB", (cols * tw, ((len(ims) + cols - 1) // cols) * th))
    for i, im in enumerate(ims):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    sheet.save(d / "sheet.png")
    small = [im.resize((480, max(1, h * 480 // w))) for im in ims]
    small[0].save(d / "burst.gif", save_all=True, append_images=small[1:], duration=200, loop=0)


def burst(call, rd, name, n, via="window"):
    d = rd / name; d.mkdir(parents=True, exist_ok=True)
    vals = []; files = []
    for i in range(n):
        dst = d / f"f{i:03d}.png"
        if via == "window":
            if not hook(f"shot {dst}").startswith("ok"):
                continue
        else:
            shutil.copyfile(Path(call("screenshot", height=540, save=True)["path"]), dst)
        files.append(dst); vals.append(round(float(whitecount.share(dst)) * 100, 4))
    if not vals:
        return {"frames": 0, "via": via, "error": "no screenshot taken"}
    try:
        record(d, files)
    except Exception as e:  # the numbers matter more than the pictures
        print(f"burst {name}: no sheet ({e})", flush=True)
    over = sum(v > whitecount.THRESHOLD * 100 for v in vals)
    return {"frames": len(vals), "via": via, "max_pct": max(vals), "mean_pct": round(sum(vals) / len(vals), 4),
            "over": over, "verdict": "specks" if over * 2 > len(vals) else "clean" if over == 0 else "mixed", "pct": vals}


WALL = (21.3, 109.95, 14.22)  # where the 600-frame bounce walk from the Kokiri spawn save ends (the cave wall)


def wait_stopped(pos, wait_frames, limit_frames=600):
    """Reads Link's position from memory until he has not moved for 20 frames. Returns where he stands, how far that
    is from the cave wall spot, and whether he stopped within the limit."""
    last = pos(); waited = 0; still = 0
    while waited < limit_frames and still < 2:
        wait_frames(10); waited += 10
        here = pos()
        still = still + 1 if sum((a - b) ** 2 for a, b in zip(here, last)) ** 0.5 < 0.005 else 0
        last = here
    off = sum((a - b) ** 2 for a, b in zip(last, WALL)) ** 0.5
    return {"pos": [round(v, 3) for v in last], "from_wall_m": round(off, 2), "stopped": still >= 2,
            "waited_frames": waited}


def written_buffers(capture_dir, shader):
    """[(index, gpu_addr, size)] of the storage buffers `shader` writes, from a capture's manifest.jsonl."""
    found = {}
    for line in (capture_dir / "manifest.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("kind") == "buffer" and e.get("shader") == shader and e.get("type") == "storage" and e.get("written"):
            found[e["index"]] = (e["index"], e["gpu_addr"], e["size"])
    return sorted(found.values())


def watch_written(call, wait_frames, capture_dir, st):
    if capture_dir is None:
        return {"error": "no capture_frame with buffers before this step"}
    bufs = written_buffers(capture_dir, st["watch_written"])
    words = int(st.get("words", 16)); reads = []
    for _ in range(int(st.get("reads", 30))):
        row = {}
        for index, addr, _size in bufs:
            try:
                r = call("read_gpu_memory", gpu_address=addr, size=4 * words, **{"as": "u32"})
                row[str(index)] = [int(v, 16) if isinstance(v, str) else int(v) for v in r.get("u32", [])]
            except Exception as e:
                row[str(index)] = str(e)
        reads.append(row); wait_frames(int(st.get("every_frames", 7)))
    return {"shader": st["watch_written"], "buffers": [{"index": i, "gpu_addr": a, "size": z} for i, a, z in bufs],
            "reads": reads}


def at_end(steps, rd, res, call, wait_frames, title, pos=None):
    out = res.setdefault("at_end", {})
    last_capture = None
    if pos is not None:
        title("waiting for Link to stand still")
        out["stand"] = wait_stopped(pos, wait_frames)
    for k, st in enumerate(steps):
        if "reject_each" in st:
            for g, group in enumerate(st["reject_each"]):
                name = st.get("name", "reject") + f"-{g:02d}"
                title(f"reject {g + 1}/{len(st['reject_each'])}")
                try:
                    call("reject_shaders", hashes=group, reject=True); wait_frames(st.get("wait", 30))
                    out[name] = dict(burst(call, rd, name, st.get("burst", 8), st.get("via", "window")), hashes=group)
                finally:
                    call("reject_shaders", hashes=group, reject=False); wait_frames(st.get("wait", 30))
        elif "burst" in st:
            title(f"burst {st['name']}")
            out[st["name"]] = burst(call, rd, st["name"], st["burst"], st.get("via", "window"))
            if pos is not None:
                out[st["name"]]["pos"] = [round(v, 3) for v in pos()]
        elif "call" in st:
            title(f"call {st['call']}")
            try:
                r = call(st["call"], timeout=st.get("timeout", 400), **st.get("params", {}))
            except Exception as e:  # keep going: later steps may still be useful
                r = {"error": str(e)}
            (rd / f"{st.get('save', st['call'] + str(k))}.json").write_text(json.dumps(r, indent=1))
            if st["call"] == "capture_frame" and isinstance(r, dict) and r.get("directory"):
                last_capture = Path(r["directory"])
        elif "watch_written" in st:
            # The storage buffers a program writes (from the last capture_frame with buffers), read from GPU
            # memory again and again at the game's own pace: does guest-visible state the shader updates (a
            # counter, a list) look the same from frame to frame?
            title(f"watching what {st['watch_written'][:8]} writes")
            out[st.get("name", "watch")] = watch_written(call, wait_frames, last_capture, st)
        elif "frames" in st:
            wait_frames(st["frames"])
