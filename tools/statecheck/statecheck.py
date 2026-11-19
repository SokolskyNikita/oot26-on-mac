#!/usr/bin/env python3
"""statecheck.py BASE: compare, draw by draw, the raster state Vulkan was asked for with the state the Metal
encoder held, and report every draw where they disagree.

Inputs (made by record.sh):
  BASE.vk.log     vkspy's log: the raw pipeline create info and dynamic state per draw
  BASE.state.log  mtlspy's MTLSPY_STATE_OUT log: the encoder's state per draw

The expected Metal value of each rule below is worked out here from the Vulkan request alone. Nothing comes from
MoltenVK, so a wrong idea inside MoltenVK about a pipeline cannot make the two sides agree by mistake.

Each draw gets one verdict per rule:
  agree      Metal holds what the request needs
  allowed    Metal differs in a way MoltenVK intends (named; see ALLOWED)
  differ     Metal holds something else: a report
  n/a        the state cannot affect this draw, or this script cannot work out what to expect (reason given)

  --rules    print the rule table and the allowed differences, then exit
  --all      list every report group (default: the 40 largest)

Exit status 1 if any draw differs or the two logs do not join one to one.

Not checked: blend, colour write mask, sample count, the contents of the depth-stencil state, bindings, and any
viewport or scissor after the first.
"""
import collections
import sys

# VkDynamicState numbers
DYN_VIEWPORT, DYN_SCISSOR, DYN_DEPTH_BIAS, DYN_STENCIL_REFERENCE = 0, 1, 3, 8
DYN_CULL_MODE, DYN_FRONT_FACE, DYN_PRIMITIVE_TOPOLOGY, DYN_STENCIL_TEST_ENABLE = 1000267000, 1000267001, 1000267002, 1000267010
DYN_RASTERIZER_DISCARD_ENABLE, DYN_DEPTH_BIAS_ENABLE, DYN_DEPTH_CLAMP_ENABLE = 1000377001, 1000377002, 1000455003
# vkspy's `set` bits
SET = dict(vp=1, sc=2, bias=4, cull=8, front=16, topo=32, biasEn=64, clampEn=128, discard=256, dtest=512, dwrite=1024,
           dcmp=2048, stest=4096, srefFront=8192, srefBack=16384)
# mtlspy's `set` bits
MSET = dict(cull=1, winding=2, fill=4, clip=8, sref=16, ds=32, bias=64, vp=128, sc=256)
# VkShaderStageFlagBits
TESS_OR_GEOMETRY, MESH = 0x2 | 0x4 | 0x8, 0x80
TRIANGLES, LINES, POINTS = "triangles", "lines", "points"
TOPOLOGY_CLASS = {0: POINTS, 1: LINES, 2: LINES, 3: TRIANGLES, 4: TRIANGLES, 5: TRIANGLES, 6: LINES, 7: LINES, 8: TRIANGLES, 9: TRIANGLES}

RULES = [
    ("topology", "A draw that is not a mesh draw and has no tessellation or geometry stage: Metal's primitive type is "
                 "the Vulkan topology (point list 0, line list 1, line strip 2, triangle list 3, triangle strip 4)."),
    ("cull", "Triangles only (Vulkan culls polygons, whatever the polygon mode). none 0 -> MTLCullModeNone 0, "
             "front 1 -> Front 1, back 2 -> Back 2."),
    ("winding", "Triangles only. Vulkan counter-clockwise 0 -> MTLWindingCounterClockwise 1, clockwise 1 -> "
                "MTLWindingClockwise 0. MoltenVK flips Y in the shader, so a triangle lands on the same pixels as in "
                "Vulkan and its winding as seen on screen is unchanged."),
    ("fill", "Triangles only. Polygon mode fill 0 -> MTLTriangleFillModeFill 0, line 1 -> Lines 1."),
    ("depthClip", "Vulkan has two switches, depth clip and depth clamp; Metal has one mode, clip 0 or clamp 1. "
                  "Depth clip is on unless depthClipEnable says otherwise, or, with no such structure, unless depth "
                  "clamp is on. clip on -> Metal clip; clip off -> Metal clamp."),
    ("depthBias", "Triangles only (Vulkan biases polygons). Bias enabled: Metal's depthBias, slopeScale, clamp are "
                  "the Vulkan constant factor, slope factor, clamp. Bias disabled: Metal's are all 0."),
    ("viewport", "The first viewport: Metal's origin, size (a negative height included) and depth range are the "
                 "Vulkan ones."),
    ("scissor", "The first scissor, cut down to the framebuffer (Metal refuses a scissor that leaves the render "
                "target): Metal's rectangle is that."),
    ("stencilRef", "Only with the stencil test on. Metal's front and back reference values are the low 8 bits of the "
                   "Vulkan ones."),
]
ALLOWED = {
    "cull both -> nothing drawn": "Metal has no 'cull both faces'. The draw must rasterize nothing, which MoltenVK does with an empty scissor; an empty Metal scissor is accepted for the cull and scissor rules.",
    "discard -> nothing drawn": "Rasterizer discard set as dynamic state: MoltenVK uses an empty scissor; an empty Metal scissor is accepted.",
    "clip and clamp both on": "Vulkan clips, then clamps to the viewport's depth range. Metal mode is clip; MoltenVK does the clamp in the shader (not checked here).",
    "clip and clamp both off": "Neither clip nor clamp. Metal mode is clamp with a 0..1 viewport depth range; MoltenVK applies the real range in the shader (not checked here).",
    "reversed depth range": "A viewport with minDepth > maxDepth: this MoltenVK build may pass the range swapped and invert Z in the shader (not checked here). Either order is accepted.",
    "triangle fan": "Metal has no triangle fan; MoltenVK draws it as a triangle list.",
}


def fields(line):
    return dict(x.split("=", 1) for x in line.split()[1:] if "=" in x)


def nums(text, kind=float):
    return tuple(kind(x) for x in text.split(","))


def close(a, b):
    return len(a) == len(b) and all(abs(x - y) <= 1e-6 * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


class Undefined(Exception):
    pass


class Draw:
    """One Vulkan draw with its pipeline as of that draw, and what it asks for."""

    def __init__(self, d, pipe, fb):
        self.d, self.p, self.fb = d, pipe, fb
        self.set = int(d["set"], 16)
        self.dyn = {int(x) for x in pipe["dyn"].split(",")} if pipe and pipe.get("dyn") else set()
        self.stages = int(pipe["stages"], 16) if pipe else 0

    def get(self, dyn_state, dkey, setbits, pkey=None, have=True):
        """The requested value: the command buffer's if the pipeline declares it dynamic, else the pipeline's."""
        if dyn_state in self.dyn:
            if self.set & setbits != setbits:
                raise Undefined(f"{dkey} is dynamic in the pipeline but no vkCmdSet call set it in this command buffer")
            return self.d[dkey]
        if not have or (pkey or dkey) not in self.p:
            raise Undefined(f"the pipeline has no static {pkey or dkey}")
        return self.p[pkey or dkey]

    def primitive_class(self):
        """(class, None) or (None, why it is not known)."""
        if self.stages & MESH:
            out = int(self.p["meshOut"])
            return (TOPOLOGY_CLASS[out], None) if out >= 0 else (None, "mesh shader output primitive not found")
        if self.stages & TESS_OR_GEOMETRY:
            return None, "tessellation or geometry stage decides the primitive"
        topo = int(self.get(DYN_PRIMITIVE_TOPOLOGY, "topo", SET["topo"], have=self.p.get("ia") == "1"))
        return (TOPOLOGY_CLASS[topo], None) if topo in TOPOLOGY_CLASS else (None, f"topology {topo}")

    def discard(self):
        return self.p.get("rs") == "1" and self.get(DYN_RASTERIZER_DISCARD_ENABLE, "discard", SET["discard"]) == "1"


def metal(m, key, default):
    """The encoder's value, or Metal's default when nothing set it on this encoder."""
    return m[key] if int(m["set"], 16) & MSET[key] else default


def was_set(m, key):
    return bool(int(m["set"], 16) & MSET[key])


def check(dr, m):
    """Yield (rule, verdict, detail, requested, metal value, set on this encoder)."""
    p = dr.p
    if p is None:
        for name, _ in RULES:
            yield name, "n/a", "no graphics pipeline was bound in this command buffer", "", "", True
        return
    try:
        discard = dr.discard()
    except Undefined as e:
        discard = False
        yield "scissor", "differ", f"request undefined: {e}", "", "", True
    cls, why_unknown = None, None
    try:
        cls, why_unknown = dr.primitive_class()
    except Undefined as e:
        why_unknown = f"request undefined: {e}"
    rt = nums(m["rt"].replace("x", ","), int)
    m_sc = nums(metal(m, "sc", f"0,0,{rt[0]},{rt[1]}"), int)
    sc_empty = m_sc[2] == 0 or m_sc[3] == 0
    tri_only = None if cls == TRIANGLES else (why_unknown or f"draws {cls}")

    def run(rule, body, skip=None):
        if discard and rule != "scissor":
            return (rule, "n/a", "rasterizer discard", "", "", True)
        if skip:
            return (rule, "n/a", skip, "", "", True)
        try:
            return (rule,) + body()
        except Undefined as e:
            return (rule, "differ", f"request undefined: {e}", "", "", True)

    def topology():
        topo = int(dr.get(DYN_PRIMITIVE_TOPOLOGY, "topo", SET["topo"], have=p.get("ia") == "1"))
        got = int(m["prim"])
        if topo == 5:
            return ("allowed" if got == 3 else "differ", "triangle fan", "fan 5", got, True)
        if topo > 4:
            return ("n/a", f"topology {topo} has no Metal primitive type", "", "", True)
        return ("agree" if got == topo else "differ", "", topo, got, True)
    yield run("topology", topology, "mesh draw" if dr.stages & MESH else why_unknown if dr.stages & TESS_OR_GEOMETRY else None)

    def cull():
        want = int(dr.get(DYN_CULL_MODE, "cull", SET["cull"]))
        got = int(metal(m, "cull", "0"))
        if want == 3:
            return ("allowed" if sc_empty else "differ", "cull both -> nothing drawn", "both 3", f"cull {got}, scissor {m_sc}", was_set(m, "cull"))
        return ("agree" if got == want else "differ", "", want, got, was_set(m, "cull"))
    yield run("cull", cull, tri_only)

    def winding():
        want = 1 - int(dr.get(DYN_FRONT_FACE, "front", SET["front"]))
        got = int(metal(m, "winding", "0"))
        return ("agree" if got == want else "differ", "", want, got, was_set(m, "winding"))
    yield run("winding", winding, tri_only)

    def fill():
        poly = int(p["poly"])
        got = int(metal(m, "fill", "0"))
        if poly == 2:
            return ("n/a", "polygon mode point has no Metal fill mode", "", "", True)
        return ("agree" if got == poly else "differ", "", poly, got, was_set(m, "fill"))
    yield run("fill", fill, tri_only)

    clamp = clip = None

    def depth_clip():
        nonlocal clamp, clip
        clamp = dr.get(DYN_DEPTH_CLAMP_ENABLE, "clampEn", SET["clampEn"]) == "1"
        clip = (not clamp) if p["clipEn"] == "-1" else p["clipEn"] == "1"
        want = 0 if clip else 1
        got = int(metal(m, "clip", "0"))
        why = "clip and clamp both on" if clip and clamp else "clip and clamp both off" if not clip and not clamp else ""
        ok = got == want
        return ("differ" if not ok else "allowed" if why else "agree", why, f"clip {int(clip)} clamp {int(clamp)} -> {want}", got, was_set(m, "clip"))
    yield run("depthClip", depth_clip, None if p.get("rs") == "1" else "no rasterization state")

    def depth_bias():
        on = dr.get(DYN_DEPTH_BIAS_ENABLE, "biasEn", SET["biasEn"]) == "1"
        got = nums(metal(m, "bias", "0,0,0"))   # depthBias, slopeScale, clamp
        if on:
            c, cl, sl = nums(dr.get(DYN_DEPTH_BIAS, "bias", SET["bias"]))   # constant, clamp, slope
            want = (c, sl, cl)
        else:
            want = (0.0, 0.0, 0.0)
        return ("agree" if close(want, got) else "differ", "", f"{'on' if on else 'off'} {want}", got, was_set(m, "bias"))
    yield run("depthBias", depth_bias, tri_only)

    def viewport():
        want = nums(dr.get(DYN_VIEWPORT, "vp", SET["vp"]))
        got = nums(metal(m, "vp", f"0,0,{rt[0]},{rt[1]},0,1"))
        why = ""
        if close(want[:4], got[:4]) and not close(want[4:], got[4:]):
            if clip is False and clamp is False and close(got[4:], (0.0, 1.0)):
                why = "clip and clamp both off"
            elif want[4] > want[5] and close(got[4:], (want[5], want[4])):
                why = "reversed depth range"
        ok = close(want, got) or bool(why)
        return ("differ" if not ok else "allowed" if why else "agree", why, want, got, was_set(m, "vp"))
    yield run("viewport", viewport, None if p.get("vs") == "1" else "no viewport state")

    def scissor():
        try:
            cull_both = cls == TRIANGLES and int(dr.get(DYN_CULL_MODE, "cull", SET["cull"])) == 3
        except Undefined:
            cull_both = False
        if (discard or cull_both) and sc_empty:
            return ("allowed", "discard -> nothing drawn" if discard else "cull both -> nothing drawn", "nothing drawn", m_sc, was_set(m, "sc"))
        if discard:
            return ("n/a", "rasterizer discard, and Metal's scissor is not empty: the pipeline may have rasterization off, which is not recorded", "", "", True)
        x, y, w, h = nums(dr.get(DYN_SCISSOR, "sc", SET["sc"]), int)
        if dr.fb:
            fw, fh = int(dr.fb["w"]), int(dr.fb["h"])
            x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, fw), min(y + h, fh)
            want = (x0, y0, max(x1 - x0, 0), max(y1 - y0, 0))
        else:
            want = (x, y, w, h)
        if want[2] == 0 or want[3] == 0:
            return ("agree" if sc_empty else "differ", "", want, m_sc, was_set(m, "sc"))
        return ("agree" if want == m_sc else "differ", "", want, m_sc, was_set(m, "sc"))
    yield run("scissor", scissor, None if p.get("vs") == "1" else "no viewport state")

    def stencil_ref():
        on = dr.get(DYN_STENCIL_TEST_ENABLE, "stest", SET["stest"], have=p.get("ds") == "1") == "1"
        if not on:
            return ("n/a", "stencil test off", "", "", True)
        if DYN_STENCIL_REFERENCE in dr.dyn:
            dr.get(DYN_STENCIL_REFERENCE, "sref", SET["srefFront"] | SET["srefBack"])
            want = nums(dr.d["sref"], int)
        else:
            want = nums(p["sref"], int)
        want = tuple(v & 0xff for v in want)
        got = tuple(v & 0xff for v in nums(metal(m, "sref", "0,0"), int))
        return ("agree" if want == got else "differ", "", want, got, was_set(m, "sref"))
    yield run("stencilRef", stencil_ref, None if p.get("ds") == "1" else "no depth-stencil state")


def main(argv):
    if "--rules" in argv:
        print("Rules: what Metal must hold for a Vulkan request\n")
        for name, text in RULES:
            print(f"  {name}: {text}")
        print("\nAllowed differences\n")
        for name, text in ALLOWED.items():
            print(f"  {name}: {text}")
        return 0
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    base = args[0]

    # The Vulkan side, in file order: a handle can be reused, so a draw's pipeline and framebuffer are the last
    # ones logged under that handle before the draw.
    pipes, fbs, draws, order = {}, {}, {}, {}
    for line in open(base + ".vk.log"):
        kind = line[:2]
        if kind == "P ":
            f = fields(line)
            f["n"] = len(order) + 1
            order[f["n"]] = f
            pipes[f["pipe"]] = f
        elif kind == "F ":
            f = fields(line)
            fbs[f["fb"]] = f
        elif kind == "D ":
            f = fields(line)
            draws[int(f["id"])] = Draw(f, pipes.get(f["pipe"]), fbs.get(f["fb"]))

    tally = collections.defaultdict(collections.Counter)   # rule -> (verdict, detail) -> draws
    groups = {}                                            # report group -> [draws, first id]
    seen = collections.Counter()
    untagged = unknown = 0
    for line in open(base + ".state.log"):
        if not line.startswith("M "):
            continue
        m = fields(line)
        tag = int(m["tag"])
        if tag < 0:
            untagged += 1
            continue
        if tag not in draws:
            unknown += 1
            continue
        seen[tag] += 1
        dr = draws[tag]
        for rule, verdict, detail, want, got, on_encoder in check(dr, m):
            tally[rule][(verdict, detail)] += 1
            if verdict == "differ":
                key = (rule, dr.p["n"] if dr.p else 0, dr.d["kind"], detail, str(want), str(got), on_encoder)
                g = groups.setdefault(key, [0, tag])
                g[0] += 1

    missing = len(set(draws) - set(seen))
    repeated = sum(1 for c in seen.values() if c > 1)
    print(f"{base}")
    print(f"join: {len(draws)} Vulkan draws, {sum(seen.values())} tagged Metal draws, {untagged} Metal draws with no tag (MoltenVK's own)")
    join_bad = missing or unknown
    if missing or unknown or repeated:
        print(f"  Vulkan draws with no Metal draw: {missing}; Metal tags unknown to Vulkan: {unknown}; Vulkan draws with several Metal draws: {repeated}")

    print(f"\n{'rule':<11}{'agree':>8}{'allowed':>9}{'differ':>8}{'n/a':>8}")
    total_differ = 0
    for rule, _ in RULES:
        t = tally[rule]
        by = collections.Counter()
        for (verdict, _detail), n in t.items():
            by[verdict] += n
        total_differ += by["differ"]
        print(f"{rule:<11}{by['agree']:>8}{by['allowed']:>9}{by['differ']:>8}{by['n/a']:>8}")
    print("\nwhy allowed or n/a")
    for rule, _ in RULES:
        for (verdict, detail), n in sorted(tally[rule].items(), key=lambda kv: -kv[1]):
            if verdict in ("allowed", "n/a"):
                print(f"  {rule:<11}{verdict:<8}{n:>7}  {detail}")

    if groups:
        ranked = sorted(groups.items(), key=lambda kv: -kv[1][0])
        limit = len(ranked) if "--all" in argv else 40
        print(f"\nreports: {total_differ} rule failures in {len(ranked)} groups (rule, pipeline, requested, Metal)")
        for (rule, pn, kind, detail, want, got, on_encoder), (n, first) in ranked[:limit]:
            p = order.get(pn)
            where = f"pipeline #{pn} ({p['pipe']}, stages {p['stages']})" if p else "no pipeline"
            note = "" if on_encoder else "  [never set on that encoder: Metal's default]"
            text = detail if not want and not got else f"requested {want}, Metal has {got}" + (f" ({detail})" if detail else "")
            print(f"  {n:>6} draws  {rule:<10} {where} {kind}: {text}{note}  first draw id {first}")
        if len(ranked) > limit:
            print(f"  ... {len(ranked) - limit} more groups (--all)")
    else:
        print("\nreports: none")
    return 1 if total_differ or join_bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
