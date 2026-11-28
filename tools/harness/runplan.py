#!/usr/bin/env python3
"""What a run of the harness will do, worked out from its spec before anything boots.

A spec entry names a profile, and the profile decides the steps:

    measure   boot, load the save, settle, walk, stand, score the end picture     (the default)
    load      boot, load the save, settle, score one picture, stop: no frame times
    boot      boot to the title screen, stop: nothing is loaded or measured (a warm-up of the shader caches)

plan() lists the steps in order, each with where it comes from: the spec, the profile, config.json, or the
harness's default. Steps the spec did not ask for are the ones to read: config.json adds checks to every run of
its save. check() refuses a key the harness does not know (a misspelt key would be ignored without a word) and a
key the profile has no step for. Nothing here launches anything; ab.py calls it, and so does tests/test_runplan.py.
"""
import difflib

PROFILES = ("measure", "load", "boot")

# Every key a spec entry may carry.
EVERY_RUN = {"label", "desc", "profile", "app", "args", "cfg", "env", "home", "server", "repeat", "build_wait",
             "lock_minutes", "cold_metal_cache"}
AFTER_LOAD = {"save", "expect_spawn", "save_index", "resave", "settle_s", "jsdbg", "server_calls", "capture",
              "flicker", "hold_file", "hold_max_s", "after_hold", "end_white_max", "cube_check",
              "keep_cube_captures", "on_corrupt"}
MEASURED = {"phase_frames", "stand_frames", "stand_first", "walk", "walk_shots", "bounce_chunk", "bounce_min_m",
            "leash_m", "turn_frames", "poll_hz", "variants", "at_end"}
KEYS = EVERY_RUN | AFTER_LOAD | MEASURED
ALLOWED = {"boot": EVERY_RUN, "load": EVERY_RUN | AFTER_LOAD, "measure": KEYS}


def profile(spec):
    return spec.get("profile", "measure")


def check(spec):
    """The mistakes in one spec entry, as a list of sentences; empty when it is fine."""
    out = []
    p = profile(spec)
    if p not in PROFILES:
        return [f"profile {p!r} is not one of {', '.join(PROFILES)}"]
    for k in sorted(spec):
        if k.startswith("_"):                         # a note for the reader, as in config.json's "_doc"
            continue
        if k not in KEYS:
            near = difflib.get_close_matches(k, sorted(KEYS), n=1)
            out.append(f"unknown key {k!r}" + (f" (did you mean {near[0]!r}?)" if near else ""))
        elif k not in ALLOWED[p]:
            out.append(f"key {k!r} has no step in profile {p!r}")
    return out


def plan(spec, config):
    """The run's steps in order: a list of (step, source). source is "spec", "profile", "config.json" or "default"."""
    p = profile(spec)
    steps = []
    add = lambda text, source: steps.append((text, source))

    def pick(key, fallback=None, config_key=True):
        """A value and where it comes from: the spec, else config.json, else the harness's default."""
        if key in spec:
            return spec[key], "spec"
        if config_key and config.get(key) is not None:
            return config[key], "config.json"
        return fallback, "default"

    if spec.get("cold_metal_cache"):
        add("set the app's Metal cache aside (cold boot)", "spec")
    add("boot to the title screen", "profile")
    if p == "boot":
        add("stop", "profile")
        return steps
    save, ssrc = pick("save")
    default_save = save == config.get("save")
    add(f"load save {save}", ssrc)
    if spec.get("resave"):
        add("save again", "spec")
    if spec.get("hold_file"):
        add(f"hold for up to {spec.get('hold_max_s', '?')} s while {spec['hold_file']} exists", "spec")
        if spec.get("after_hold") == "stop":
            add("stop", "spec")
            return steps
    quiet, qsrc = pick("settle_s", 3, config_key=False)
    add(f"settle (no pipeline build for {quiet} s)", qsrc)
    for key, text in (("server_calls", "debug-server calls"), ("capture", "frame capture"), ("flicker", "flicker burst")):
        if spec.get(key):
            add(text, "spec")
    if p == "measure":
        frames, fsrc = pick("phase_frames", 300, config_key=False)
        times = f" x{len(spec['variants'])} variants" if spec.get("variants") else ""
        if spec.get("stand_first"):
            add(f"stand {frames} frames{times}", "spec")
        add(f"walk {frames} frames ({spec.get('walk', 'bounce')}){times}", fsrc)
        add(f"stand {spec.get('stand_frames', frames)} frames{times}", fsrc)
        if spec.get("at_end"):
            add("at_end steps", "spec")
    add("end picture, scored for corruption", "profile")
    # config.json's picture checks apply to runs of its own save only; a spec's own value always applies.
    limit, lsrc = pick("end_white_max") if default_save or "end_white_max" in spec else (None, None)
    if limit is not None:
        add(f"clipped-white limit {limit} %", lsrc)
    cube, csrc = pick("cube_check") if default_save or "cube_check" in spec else (0, None)
    if cube:
        add(f"cube check: {cube} frame captures", csrc)
    if spec.get("on_corrupt"):
        add("on_corrupt steps if the picture is corrupt", "spec")
    add("stop", "profile")
    return steps


def text(spec, config):
    """One line for the run: label [profile]: step -> step -> ...; a step config.json adds says so."""
    parts = [f"{s} (from config.json)" if src == "config.json" else s for s, src in plan(spec, config)]
    return f"{spec.get('label', '?')} [{profile(spec)}]: " + " → ".join(parts)


def main():
    print(__doc__.strip().split("\n\n")[1])
    for name, keys in (("every run", EVERY_RUN), ("after the load (profiles load and measure)", AFTER_LOAD),
                       ("the measured phases (profile measure)", MEASURED)):
        print(f"\nkeys for {name}:\n  " + " ".join(sorted(keys)))


if __name__ == "__main__":
    main()
