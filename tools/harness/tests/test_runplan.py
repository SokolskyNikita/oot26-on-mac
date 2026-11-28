#!/usr/bin/env python3
"""Offline tests of runplan.py: the steps of a run, the profiles, and which spec keys are refused. Also checks every
spec file in the repository, and the spec of every run recorded on this machine, against the list of known keys.

    python3 -m unittest discover -s tools/harness/tests -v
"""
import json
import sys
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parents[1]
sys.path.insert(0, str(HARNESS))
import runplan as rp  # noqa: E402

CONFIG = json.loads((HARNESS / "config.json").read_text())
steps = lambda spec, config=CONFIG: [s for s, _ in rp.plan(spec, config)]
sources = lambda spec, config=CONFIG: dict(rp.plan(spec, config))


class Plan(unittest.TestCase):
    def test_default_run_names_what_config_json_adds(self):
        src = sources({"label": "x"})
        inherited = [s for s, where in src.items() if where == "config.json"]
        self.assertEqual(len(inherited), 2, inherited)      # the save and the white limit
        line = rp.text({"label": "x"}, CONFIG)
        self.assertIn("clipped-white limit 1.0 % (from config.json)", line)
        self.assertTrue(line.startswith("x [measure]: boot to the title screen"))

    def test_cube_check_is_off_unless_asked(self):
        self.assertEqual(CONFIG["cube_check"], 0)           # the repository's default
        self.assertFalse(any("cube check" in s for s in steps({"label": "x"})))
        self.assertIn("cube check: 8 frame captures", steps({"label": "x", "cube_check": 8}))      # one spec
        on = dict(CONFIG, cube_check=8)                     # every run of the default save
        self.assertIn("cube check: 8 frame captures (from config.json)", rp.text({"label": "x"}, on))
        self.assertFalse(any("cube check" in s for s in steps({"label": "x", "cube_check": 0}, on)))
        self.assertIn("cube check: 8 frame captures (from config.json)", rp.text({"label": "x", "profile": "load"}, on))

    def test_another_save_gets_no_config_checks(self):
        st = steps({"label": "x", "save": "gerudo-valley"})
        self.assertFalse(any("cube check" in s or "clipped-white" in s for s in st))
        self.assertEqual(sources({"label": "x", "save": "gerudo-valley"})["load save gerudo-valley"], "spec")
        st = steps({"label": "x", "save": "gerudo-valley", "cube_check": 4})   # its own always applies
        self.assertIn("cube check: 4 frame captures", st)

    def test_boot_profile(self):
        self.assertEqual(steps({"label": "x", "profile": "boot"}), ["boot to the title screen", "stop"])
        self.assertEqual(steps({"label": "x", "profile": "boot", "cold_metal_cache": True})[0],
                         "set the app's Metal cache aside (cold boot)")

    def test_load_profile_has_no_measured_phase(self):
        st = steps({"label": "x", "profile": "load"})
        self.assertFalse(any(s.startswith(("walk", "stand")) for s in st))
        self.assertEqual(st[-2:], ["clipped-white limit 1.0 %", "stop"])
        self.assertIn("end picture, scored for corruption", st)

    def test_measure_phases(self):
        st = steps({"label": "x", "phase_frames": 600, "stand_first": True, "walk": "route"})
        self.assertEqual([s for s in st if s.startswith(("walk", "stand"))],
                         ["stand 600 frames", "walk 600 frames (route)", "stand 600 frames"])

    def test_hold_then_stop(self):
        st = steps({"label": "x", "hold_file": "/tmp/HOLD", "hold_max_s": 90, "after_hold": "stop"})
        self.assertEqual(st[-1], "stop"); self.assertFalse(any(s.startswith("walk") for s in st))


class Check(unittest.TestCase):
    def test_fine(self):
        self.assertEqual(rp.check({"label": "x", "cfg": {}, "phase_frames": 300, "_note": "anything"}), [])

    def test_misspelt_key(self):
        self.assertEqual(rp.check({"label": "x", "cube_chek": 0}), ["unknown key 'cube_chek' (did you mean 'cube_check'?)"])

    def test_unknown_profile(self):
        self.assertEqual(len(rp.check({"label": "x", "profile": "warm"})), 1)

    def test_key_without_a_step_in_the_profile(self):
        self.assertEqual(rp.check({"label": "x", "profile": "boot", "save": "kokiri-forest"}),
                         ["key 'save' has no step in profile 'boot'"])
        self.assertEqual(rp.check({"label": "x", "profile": "load", "phase_frames": 300}),
                         ["key 'phase_frames' has no step in profile 'load'"])
        self.assertEqual(rp.check({"label": "x", "profile": "load", "save": "a", "cube_check": 0}), [])


def spec_entries(path):
    try:
        data = json.loads(Path(path).read_text())
    except (ValueError, OSError):
        return []
    return [e for e in data if isinstance(e, dict) and "label" in e] if isinstance(data, list) else []


class RealSpecs(unittest.TestCase):
    def test_every_spec_file_in_the_repository(self):
        files = [f for d in ("tools", "wip", "research") for f in (REPO / d).rglob("*.json")
                 if "runs" not in f.parts and "local" not in f.parts and "build" not in f.parts]
        n = 0
        for f in files:
            for e in spec_entries(f):
                n += 1
                self.assertEqual(rp.check(e), [], f"{f}: {e.get('label')}")
        self.assertGreater(n, 20)
        print(f"({n} spec entries in the repository checked) ", end="", file=sys.stderr)

    def test_every_recorded_run(self):
        results = sorted((HARNESS / "runs").glob("ab-*/*/result.json"))
        if not results:
            self.skipTest("no recorded runs on this machine (tools/harness/runs is local data)")
        n = 0
        for f in results:
            try:
                spec = json.loads(f.read_text()).get("spec")
            except ValueError:
                continue
            if isinstance(spec, dict):
                n += 1
                unknown = [e for e in rp.check(spec) if e.startswith("unknown key")]
                self.assertEqual(unknown, [], f)
                rp.text(spec, CONFIG)                       # and its plan can be written
        print(f"({n} recorded runs' specs checked) ", end="", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
