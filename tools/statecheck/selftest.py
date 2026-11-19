#!/usr/bin/env python3
"""selftest.py --src MOLTENVK_TREE: prove the Vulkan-to-Metal state check detects real faults.

For each fault in FAULTS it puts one deliberate bug into MoltenVK's encoder-state code, builds that library, replays
the recorded trace through both recorders (record.sh) and runs statecheck.py. A fault passes when the
rule it should break reports draws. A fault that leaves every recorded Metal value the same as the unfaulted library's
has no effect on this trace: that is printed as "no effect", proves nothing either way, and does not fail the run.
The MoltenVK source is put back after every fault, the tree is rebuilt at the end, and the library that was there
before is put back byte for byte.

  --src DIR     MoltenVK source tree, already configured and built with CMake (required)
  --build DIR   its CMake build directory, relative to --src (default build-par)
  --only a,b    run only these faults
  --reuse       keep a fault library that is already built

Fault libraries go to runs/faults/<name>/libMoltenVK.dylib, recordings to runs/fault-<name>.*, and each fault's
full report to runs/fault-<name>.check.txt. TRACE and EDEN_CLI pass through to record.sh.
Do not run while anything else builds in that MoltenVK tree. Exit status 1 if a fault goes undetected.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
STATE_FILE = "MoltenVK/MoltenVK/Commands/MVKCommandEncoderState.mm"

# name, the rule that must report it, what the bug is, regex of the code to replace, the replacement.
# Each regex must match exactly once.
FAULTS = [
    ("winding-flipped", "winding", "the front-face winding is set inverted",
     r"static_cast<MTLWinding>\(data\.frontFace\)",
     "static_cast<MTLWinding>(data.frontFace ^ 1)"),
    ("cull-kept-across-encoders", "cull",
     "a new Metal encoder starts with MoltenVK still believing the previous encoder's cull mode is set, so it is not applied again",
     r"memset\(static_cast<MVKMetalGraphicsCommandEncoderStateQuickReset\*>\(this\), 0, offsetof\(MVKMetalGraphicsCommandEncoderStateQuickReset, MEMSET_RESET_LINE\)\);",
     "uint8_t faultKeepCull = _cullMode; memset(static_cast<MVKMetalGraphicsCommandEncoderStateQuickReset*>(this), 0, offsetof(MVKMetalGraphicsCommandEncoderStateQuickReset, MEMSET_RESET_LINE)); _cullMode = faultKeepCull;"),
    ("bias-not-cleared", "depthBias", "depth bias is not set back to zero when a draw has it disabled",
     r"(else if \(wasEnabled\) \{\s*_flags\.remove\(MVKMetalRenderEncoderStateFlag::DepthBiasEnable\);)\s*\[encoder setDepthBias:0 slopeScale:0 clamp:0\];",
     r"\1"),
    ("depth-clamp-ignored", "depthClip", "a request for depth clamp is ignored, so Metal stays in clip mode",
     r"bool clamp = PICK_STATE\(DepthClampEnable\)->enable\.has\(MVKRenderStateEnableFlag::DepthClamp\);",
     "bool clamp = false;"),
    ("viewport-flip-lost", "viewport", "a viewport with a negative height (a Y flip) is passed to Metal with the height made positive",
     r"mtlViewports\[i\] = mvkMTLViewportFromVkViewport\(adjustedViewports\[i\]\);",
     "mtlViewports[i] = mvkMTLViewportFromVkViewport(adjustedViewports[i]); if (mtlViewports[i].height < 0) { mtlViewports[i].originY += mtlViewports[i].height; mtlViewports[i].height = -mtlViewports[i].height; }"),
    ("viewport-stale", "viewport", "a changed viewport is not applied unless the number of viewports changed",
     r"if \(_numViewports != numViewports \|\| !mvkAreEqual\(_viewports, adjustedViewports, numViewports\)\) \{",
     "if (_numViewports != numViewports) {"),
    ("scissor-stale", "scissor", "a changed scissor is not applied unless the number of scissors changed",
     r"\(_numScissors != data\.numScissors \|\| !mvkAreEqual\(_scissors, scissors, data\.numScissors\)\)",
     "(_numScissors != data.numScissors)"),
]
RULE_NAMES = ["topology", "cull", "winding", "fill", "depthClip", "depthBias", "viewport", "scissor", "stencilRef"]


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def build(src, build_dir):
    r = subprocess.run(["cmake", "--build", build_dir], cwd=src, capture_output=True, text=True)
    if r.returncode:
        sys.stdout.write(r.stdout[-3000:] + r.stderr[-3000:])
    return r.returncode == 0


def main(argv):
    opt = {"--src": "", "--build": "build-par", "--only": ""}
    reuse = "--reuse" in argv
    for i, a in enumerate(argv):
        if a in opt:
            opt[a] = argv[i + 1]
    if not opt["--src"]:
        print(__doc__)
        return 2
    src, build_dir = os.path.abspath(opt["--src"]), opt["--build"]
    faults = [f for f in FAULTS if not opt["--only"] or f[0] in opt["--only"].split(",")]
    source = os.path.join(src, STATE_FILE)
    lib = os.path.realpath(os.path.join(src, build_dir, "MoltenVK", "libMoltenVK.dylib"))
    out_root = os.path.join(RUNS, "faults")
    os.makedirs(out_root, exist_ok=True)

    original = open(source).read()
    for name, _rule, _what, pattern, _new in faults:
        n = len(re.findall(pattern, original))
        if n != 1:
            print(f"fault {name}: its pattern matches {n} times in {STATE_FILE}, expected 1. Nothing was changed.")
            return 2
    saved = os.path.join(out_root, "libMoltenVK.before-selftest.dylib")
    lib_before = md5(lib)
    shutil.copyfile(lib, saved)
    if not build(src, build_dir):
        print("the unmodified tree does not build; nothing was changed")
        return 2
    fresh = md5(lib)   # a build of the untouched source, which need not be byte-identical to the library found

    built = {}
    try:
        for name, _rule, _what, pattern, new in faults:
            dest = os.path.join(out_root, name, "libMoltenVK.dylib")
            if reuse and os.path.exists(dest):
                built[name] = dest
                continue
            open(source, "w").write(re.sub(pattern, new, original, count=1))
            ok = build(src, build_dir)
            open(source, "w").write(original)
            if not ok:
                print(f"fault {name}: build failed")
                continue
            if md5(lib) in (lib_before, fresh):
                print(f"fault {name}: the library did not change")
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(lib, dest)
            built[name] = dest
            print(f"built {name}", flush=True)
    finally:
        open(source, "w").write(original)
        restored = build(src, build_dir)
        rebuilt = md5(lib) if restored else None
        shutil.copyfile(saved, lib)   # a new modification time, so the build system does not relink over it
        how = ("identical to the library found beforehand" if rebuilt == lib_before else
               "identical to a build of the untouched source made at the start" if rebuilt == fresh else
               "DIFFERENT from both the library found beforehand and a build of the untouched source" if restored else "FAILED")
        print(f"source restored; the rebuild is {how}; the library found beforehand was put back (md5 {md5(lib)})", flush=True)

    def metal_values(label):
        keep = ("tag", "kind", "prim", "set", "cull", "winding", "fill", "clip", "bias", "vp", "sc", "sref")
        rows = []
        for line in open(os.path.join(RUNS, label + ".state.log")):
            if line.startswith("M "):
                f = dict(x.split("=", 1) for x in line.split()[1:])
                rows.append(tuple(f[k] for k in keep))
        return rows

    subprocess.run([os.path.join(HERE, "record.sh"), "fault-none", saved], capture_output=True, text=True)
    baseline = metal_values("fault-none")
    undetected = []
    print(f"\n{'fault':<27}{'must break':<11}{'result':<10}draws reported per rule")
    for name, rule, _what, _pattern, _new in faults:
        if name not in built:
            undetected.append(name)
            print(f"{name:<27}{rule:<11}{'NOT BUILT':<10}")
            continue
        label = f"fault-{name}"
        subprocess.run([os.path.join(HERE, "record.sh"), label, built[name]], capture_output=True, text=True)
        chk = subprocess.run([sys.executable, os.path.join(HERE, "statecheck.py"), os.path.join(RUNS, label)], capture_output=True, text=True)
        open(os.path.join(RUNS, label + ".check.txt"), "w").write(chk.stdout + chk.stderr)
        differ = {}
        for line in chk.stdout.split("why allowed")[0].splitlines():
            f = line.split()
            if len(f) == 5 and f[0] in RULE_NAMES:
                differ[f[0]] = int(f[3])
        hit = differ.get(rule, 0) > 0
        joined = "Vulkan draws with no Metal draw" not in chk.stdout
        no_effect = not hit and not any(differ.values()) and metal_values(label) == baseline
        if not hit and not no_effect:
            undetected.append(name)
        shown = ", ".join(f"{k} {v}" for k, v in differ.items() if v) or "none"
        print(f"{name:<27}{rule:<11}{'detected' if hit else 'no effect' if no_effect else 'MISSED':<10}{shown}{'' if joined else '  [logs did not join one to one]'}", flush=True)
    print("\nall faults detected" if not undetected else f"\nNOT detected: {', '.join(undetected)}")
    return 1 if undetected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
