#!/usr/bin/env python3
"""Offline tests of test_app.py on made-up apps and cache folders: nothing is signed, booted or read from the real
Metal caches.

    python3 -m unittest discover -s tools/harness/tests -v
"""
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metalcache as mc  # noqa: E402
import test_app as ta  # noqa: E402
from test_metalcache import NEW, OLD, make_cache  # noqa: E402


class TestApps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.uc, self.apps = root / "C", root / "test-apps"; self.uc.mkdir()
        self.pinned = root / "build/app/lichii.app"
        (self.pinned / "Contents/MacOS").mkdir(parents=True); (self.pinned / "Contents/Frameworks").mkdir()
        (self.pinned / "Contents/MacOS/lichii").write_bytes(b"pinned binary")
        (self.pinned / "Contents/Frameworks/libMoltenVK.dylib").write_bytes(b"...04ac9bef...")
        with open(self.pinned / "Contents/Info.plist", "wb") as f:
            plistlib.dump({"CFBundleIdentifier": mc.LICHII_ID, "CFBundleName": "Lichii"}, f)
        self.gold_cache = make_cache(self.uc, mc.LICHII_ID, NEW, 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, **kw):
        return ta.make(name, pinned=self.pinned, apps=self.apps, user_cache=self.uc, do_sign=False,
                       cache_id="04ac9bef", **kw)

    def test_make_sets_the_id_and_leaves_the_caches_alone(self):
        made = self.make("pr2665")
        app = Path(made["app"])
        self.assertEqual(mc.bundle_id(app), mc.LICHII_ID + ".pr2665")
        self.assertEqual(plistlib.loads((app / "Contents/Info.plist").read_bytes())["CFBundleName"], "Lichii")
        self.assertEqual(mc.bundle_id(self.pinned), mc.LICHII_ID)             # the pinned app is not touched
        self.assertEqual(Path(made["metal_cache"]), self.uc / (mc.LICHII_ID + ".pr2665") / "com.apple.metal")
        self.assertFalse(mc.cache_dir(app, self.uc).exists())                 # its own cache, empty until it boots
        self.assertEqual(mc.stamps(self.gold_cache), NEW)                     # the pinned cache is not touched
        self.assertTrue(made["pipeline_cache_id_matches"])
        self.assertEqual(json.loads((self.apps / "pr2665/test-app.json").read_text())["bundle_id"], made["bundle_id"])

    def test_own_binaries(self):
        lib = Path(self.tmp.name) / "other.dylib"; lib.write_bytes(b"...deadbeef...")
        binary = Path(self.tmp.name) / "lichii.new"; binary.write_bytes(b"new binary")
        made = self.make("mvk", moltenvk=lib, lichii=binary)
        app = Path(made["app"])
        self.assertEqual((app / "Contents/MacOS/lichii").read_bytes(), b"new binary")
        self.assertFalse(made["pipeline_cache_id_matches"])                   # the first boot will be cold
        self.assertEqual((app / "Contents/Frameworks/libMoltenVK.dylib").read_bytes(), b"...deadbeef...")

    def test_force_keeps_the_apps_own_cache(self):
        self.make("keep")
        own = make_cache(self.uc, mc.LICHII_ID + ".keep", OLD, 500)
        self.make("keep", force=True)
        self.assertEqual(mc.stamps(own), OLD)

    def test_make_twice_needs_force(self):
        self.make("a")
        with self.assertRaises(SystemExit):
            self.make("a")
        self.make("a", force=True)

    def test_ensure_follows_the_pinned_app(self):
        kw = dict(pinned=self.pinned, apps=self.apps, user_cache=self.uc, do_sign=False, cache_id="04ac9bef")
        app, what = ta.ensure("play", **kw)
        self.assertEqual(what, "made"); self.assertTrue(ta.current(app, self.pinned))
        self.assertEqual(ta.ensure("play", **kw)[1], "kept")
        own = make_cache(self.uc, mc.LICHII_ID + ".play", NEW, 2000)          # its cache, after a boot
        (self.pinned / "Contents/Frameworks/libMoltenVK.dylib").write_bytes(b"a new MoltenVK 04ac9bef")
        self.assertFalse(ta.current(app, self.pinned))
        self.assertEqual(ta.ensure("play", **kw)[1], "remade")
        self.assertEqual((app / "Contents/Frameworks/libMoltenVK.dylib").read_bytes(), b"a new MoltenVK 04ac9bef")
        self.assertEqual(mc.bundle_id(app), mc.LICHII_ID + ".play"); self.assertTrue(own.exists())
        (self.pinned / "Contents/MacOS/nx2_switches.txt").write_text("A=1")   # a file the copy lacks
        self.assertEqual(ta.ensure("play", **kw)[1], "remade")

    def test_ensure_leaves_an_app_with_its_own_binaries(self):
        binary = Path(self.tmp.name) / "lichii.new"; binary.write_bytes(b"new binary")
        self.make("pr", lichii=binary)
        app, what = ta.ensure("pr", pinned=self.pinned, apps=self.apps, user_cache=self.uc, do_sign=False)
        self.assertEqual(what, "own binaries")
        self.assertEqual((app / "Contents/MacOS/lichii").read_bytes(), b"new binary")

    def test_names(self):
        for bad in ("", "Play", "a b", "../x", ".hidden", "x" * 40):
            with self.assertRaises(SystemExit, msg=bad):
                ta.check_name(bad)
        self.assertEqual(ta.check_name("pr-2665"), "pr-2665")

    def test_list_and_clean(self):
        self.make("play")
        self.assertIn("play", [r["name"] for r in ta.listing(self.apps, self.uc)])   # listed before its first boot
        make_cache(self.uc, mc.LICHII_ID + ".play", NEW, 2000)                # as after its first boot
        make_cache(self.uc, mc.LICHII_ID + ".p99probe", OLD, 500)             # an old id whose app is gone
        rows = {r["name"]: r for r in ta.listing(self.apps, self.uc)}
        self.assertEqual(sorted(rows), ["(pinned)", "p99probe", "play"])
        self.assertTrue(rows["play"]["app"]); self.assertIsNone(rows["p99probe"]["app"])
        self.assertTrue(rows["p99probe"]["stale"]); self.assertFalse(rows["(pinned)"]["stale"])
        self.assertEqual(len(ta.clean("play", self.apps, self.uc)), 2)        # the app folder and its cache
        self.assertEqual(len(ta.clean("p99probe", self.apps, self.uc)), 1)    # only a cache
        self.assertEqual(ta.clean("p99probe", self.apps, self.uc), [])
        self.assertEqual([r["name"] for r in ta.listing(self.apps, self.uc)], ["(pinned)"])
        self.assertTrue(self.gold_cache.exists())                             # the pinned cache is never cleaned


if __name__ == "__main__":
    unittest.main()
