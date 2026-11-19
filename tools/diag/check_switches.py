#!/usr/bin/env python3
"""check_switches.py: compares the catalogue (switches.json) with what the pinned sources read, and README.md with
the catalogue. Standard library only; exits 1 when it reports anything.

Names the sources read, from build/src/lichii/src (tests, android and fuzz folders left out) and
build/src/moltenvk/MoltenVK/MoltenVK:
  - any getenv("NAME") / mvkGetEnvVar…("NAME") literal;
  - every string literal that is a whole environment name with a Lichii, dynarmic, path-60, Eglantine, Mesa or RADV
    prefix, which covers the helper readers (EnvSeconds, EnvInt, EnvFlagSet, number(), tuned(), the TC threshold
    tuples, the nx2_switches.h allow-list) since each takes the name as such a literal;
  - MVK_CONFIG_<name> of every MVK_CONFIG_MEMBER in MVKConfigMembers.def;
  - names added by patches/experiments/*.patch (these must be catalogued with in_pinned_build false).
Reports:
  1. names read by the sources that are neither catalogued (a record or its companions) nor in "not_diagnostic";
  2. catalogued environment switches of the pinned build that the sources no longer read, records whose source file
     no longer mentions them, settings and debug calls the sources no longer have, experiment-only records whose
     patch does not add them;
  3. records and companions that README.md does not name, and environment-like names README.md gives in backticks
     that the catalogue does not hold;
  4. records with missing fields or values outside the documented sets.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
LICHII = REPO / "build/src/lichii"
MVK = REPO / "build/src/moltenvk"
SRC_EXT = {".cpp", ".h", ".inc", ".mm", ".hpp", ".c", ".m", ".def"}
PREFIX = r"(?:EDEN|P60|DYNARMIC|EGLANTINE|LICHII|MESA|RADV|MVK)_[A-Z0-9_]*[A-Z0-9]"
OWNERS = {"lichii", "ours-lichii-patch", "moltenvk", "ours-moltenvk-patch", "dynarmic", "apple", "harness"}
KINDS = {"env", "setting", "debug-call", "always-on", "tool"}
SETTABLE = {"env", "nx2_switches.txt", "spec env", "LSEnvironment", "debug call", "setting"}
LEVELS = {0, 1, 2, "3a", "3b", 4, 5, 6, "hygiene", "not-for-timing"}
TIERS = {"proven": "### Proven here", "untested": "### Untested here, worth trying", "other": "### Everything else, by level"}
FIELDS = ("name", "owner", "level", "kind", "output", "granularity", "cost", "settable_from", "in_pinned_build",
          "last_checked", "reader", "hazards")
SOURCE_OWNERS = {"lichii", "ours-lichii-patch", "moltenvk", "ours-moltenvk-patch", "dynarmic"}


def files(root, skip=()):
    for p in root.rglob("*"):
        if p.suffix in SRC_EXT and p.is_file() and not any(f"/{s}/" in str(p) for s in skip):
            yield p


def scan_sources():
    """{name: first file:line} of every environment name the pinned sources read."""
    found = {}
    lit = re.compile(r'"(' + PREFIX + r')"')
    get = re.compile(r'(?:getenv|mvkGetEnvVar\w*)\(\s*"([A-Za-z_][A-Za-z0-9_]*)"')
    for root, skip in ((LICHII / "src", ("tests", "android", "fuzz")), (MVK / "MoltenVK/MoltenVK", ())):
        for p in files(root, skip):
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                for m in list(lit.finditer(line)) + list(get.finditer(line)):
                    found.setdefault(m[1], f"{p.relative_to(REPO)}:{i}")
    defs = MVK / "MoltenVK/MoltenVK/Utility/MVKConfigMembers.def"
    for i, line in enumerate(defs.read_text().splitlines(), 1):
        m = re.match(r"\s*MVK_CONFIG_MEMBER(?:_STRING)?\([^,]+,[^,]+,\s*(\w+)\)", line)
        if m:
            found.setdefault("MVK_CONFIG_" + m[1], f"{defs.relative_to(REPO)}:{i}")
    return found


def scan_experiments():
    out = {}
    for p in sorted((REPO / "patches/experiments").glob("*.patch")):
        for line in p.read_text(errors="replace").splitlines():
            if line.startswith("+"):
                for m in re.finditer(r'"(' + PREFIX + r')"', line):
                    out.setdefault(m[1], str(p.relative_to(REPO)))
    return out


def source_path(src):
    """A record's source field -> the file it names (Lichii src/…, MoltenVK/…, tools/…, patches/…)."""
    f = src.split(":")[0]
    for base in (LICHII, MVK, REPO):
        if (base / f).exists():
            return base / f
    return None


def main():
    cat = json.loads((HERE / "switches.json").read_text())
    recs = cat["switches"]
    nd = cat.get("not_diagnostic", {})
    readme = (HERE / "README.md").read_text()
    problems = []
    srcs = scan_sources()
    exps = scan_experiments()

    catalogued = {}
    for r in recs:
        for n in [r["name"]] + r.get("companions", []):
            if n in catalogued:
                problems.append(f"catalogue: {n} appears twice")
            catalogued[n] = r

    # 4. fields
    for r in recs:
        miss = [f for f in FIELDS if f not in r]
        if miss:
            problems.append(f"record {r.get('name')}: missing {', '.join(miss)}")
            continue
        if r["owner"] not in OWNERS or r["kind"] not in KINDS or r["level"] not in LEVELS or \
                not set(r["settable_from"]) <= SETTABLE:
            problems.append(f"record {r['name']}: owner, kind, level or settable_from outside the documented sets")

    # 1. read by the sources, not catalogued
    for n, where in sorted(srcs.items()):
        if n not in catalogued and n not in nd:
            problems.append(f"read by the source, not in switches.json or not_diagnostic: {n} ({where})")
    for n, where in sorted(exps.items()):
        if n not in catalogued and n not in nd:
            problems.append(f"added by an experiment patch, not in switches.json or not_diagnostic: {n} ({where})")

    # 2. catalogued, no longer read
    settings_text = "".join((LICHII / f).read_text(errors="replace") for f in
                            ("src/common/settings.h", "src/frontend_common/config.cpp"))
    debug_text = (LICHII / "src/core/debugger/nx2_debug_tools.cpp").read_text(errors="replace")
    for r in recs:
        names = [r["name"]] + r.get("companions", [])
        if r["kind"] == "env" and r["owner"] in SOURCE_OWNERS:
            for n in names:
                if r["in_pinned_build"] and n not in srcs:
                    problems.append(f"catalogued but not read by the pinned sources: {n}")
                if not r["in_pinned_build"] and n not in exps:
                    problems.append(f"catalogued as experiment-only but no experiment patch adds it: {n}")
        if r["kind"] == "setting" and f'"{r["name"]}"' not in settings_text:
            problems.append(f"setting {r['name']} is not in settings.h or config.cpp")
        if r["kind"] == "debug-call":
            for n in names:
                call = n.split(" ")[0]
                if f'{{"{call}", ' not in debug_text:
                    problems.append(f"debug call {call} is not a handler in nx2_debug_tools.cpp")
        src = r.get("source")
        if src and r["owner"] != "harness":
            f = source_path(src)
            if f is None:
                problems.append(f"record {r['name']}: source {src} does not exist")
            elif r["kind"] == "env" and re.sub(r"^MVK_CONFIG_", "", r["name"]) not in f.read_text(errors="replace"):
                problems.append(f"record {r['name']}: {src} does not mention it")

    # 3a. tiers: every record has one, a proven or untested record says why (verdict), and README.md lists the record
    #     under its tier's heading
    heads = {t: readme.find(h) for t, h in TIERS.items()}
    for t, at in heads.items():
        if at < 0:
            problems.append(f"README.md has no heading {TIERS[t]!r}")
    bounds = sorted((at, t) for t, at in heads.items() if at >= 0)
    for r in recs:
        t = r.get("tier")
        if t not in TIERS:
            problems.append(f"record {r['name']}: tier missing or not one of {sorted(TIERS)}")
            continue
        if t != "other" and not r.get("verdict"):
            problems.append(f"record {r['name']}: tier {t} without a verdict")
        first = bounds[0][0] if bounds else 0      # rows before the first tier heading are other tables
        at = readme.find(f"| `{r['name']}` ", first)
        if at >= 0 and bounds:
            under = [name for start, name in bounds if start <= at]
            if not under or under[-1] != t:
                problems.append(f"record {r['name']}: tier {t}, but README.md lists it under {under[-1] if under else 'no tier heading'}")

    # 3. README
    for n in catalogued:
        if n not in readme:
            problems.append(f"in switches.json, not named in README.md: {n}")
    for m in set(re.findall(r"`(" + PREFIX + r"|MTL_[A-Z0-9_]+)`", readme)):
        if m not in catalogued and m not in nd:
            problems.append(f"named in README.md, not in switches.json: {m}")

    for p in problems:
        print(p)
    levels = {}
    for r in recs:
        levels[str(r["level"])] = levels.get(str(r["level"]), 0) + 1
    print(f"{len(recs)} records ({len(catalogued)} names with companions), {len(nd)} not diagnostic; "
          f"{len(srcs)} names read by the pinned sources, {len(exps)} added by experiment patches; by level: " +
          ", ".join(f"{k} {v}" for k, v in levels.items()))
    print(f"{len(problems)} problem(s)" if problems else "catalogue, sources and README agree")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
