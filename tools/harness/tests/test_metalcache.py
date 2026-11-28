#!/usr/bin/env python3
"""Offline tests of metalcache.py: made-up cache folders, plus this machine's recorded runs when there are any.
No emulator, nothing launched.

    python3 -m unittest discover -s tools/harness/tests -v
"""
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import metalcache as mc  # noqa: E402

OLD = {"functions": "1f" * 32, "libraries": "bd" * 32}
NEW = {"functions": "f3" * 32, "libraries": "7f" * 32}


def make_app(root, name, bundle):
    app = root / f"{name}.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents/Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": bundle}, f)
    return app


def make_cache(user_cache, bundle, stamps, mtime, data_bytes=4 << 20):
    cache = user_cache / bundle / "com.apple.metal"
    for sub, kind in (("16777235_467", "functions"), ("32024", "libraries")):
        d = cache / sub; d.mkdir(parents=True)
        (d / f"{kind}.list").write_bytes(b"\x01\x00\x00\x00" + bytes.fromhex(stamps[kind]) + b"entries")
        (d / f"{kind}.data").write_bytes(b"\0" * (data_bytes // 2))
        os.utime(d / f"{kind}.list", (mtime, mtime))
    return cache


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.uc = self.root / "C"; self.uc.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_follows_the_apps_bundle_id(self):
        gold = make_app(self.root, "gold", mc.LICHII_ID)
        probe = make_app(self.root, "probe", mc.LICHII_ID + ".p99probe")
        self.assertEqual(mc.cache_dir(gold, self.uc), self.uc / mc.LICHII_ID / "com.apple.metal")
        self.assertEqual(mc.cache_dir(probe, self.uc), self.uc / (mc.LICHII_ID + ".p99probe") / "com.apple.metal")

    def test_stamps_and_size(self):
        cache = make_cache(self.uc, mc.LICHII_ID, NEW, 1000)
        self.assertEqual(mc.stamps(cache), NEW)
        self.assertEqual(mc.data_size(cache), 4 << 20)
        self.assertEqual(mc.stamps(self.uc / "nothing/com.apple.metal"), {})
        self.assertEqual(mc.data_size(self.uc / "nothing/com.apple.metal"), 0)

    def test_stale_only_against_a_later_cache_with_another_stamp(self):
        old = make_cache(self.uc, mc.LICHII_ID + ".p99probe", OLD, 1000)
        self.assertFalse(mc.stale(old))                                   # alone: nothing to compare with
        same = make_cache(self.uc, mc.LICHII_ID + ".jit2180", OLD, 2000)
        self.assertFalse(mc.stale(old))                                   # a later one with the same stamp
        new = make_cache(self.uc, mc.LICHII_ID, NEW, 3000)
        self.assertTrue(mc.stale(old)); self.assertTrue(mc.stale(same))   # the system changed after both
        self.assertFalse(mc.stale(new))                                   # older caches don't make the new one stale
        make_cache(self.uc, "org.mozilla.firefox", OLD, 9000)             # another program's cache is ignored
        self.assertFalse(mc.stale(new))

    def test_snapshot_and_expect_cold(self):
        gold = make_app(self.root, "gold", mc.LICHII_ID)
        s = mc.snapshot(gold, self.uc)                                    # never ran: no cache
        self.assertEqual(mc.expect_cold(s), "empty Metal cache")
        make_cache(self.uc, mc.LICHII_ID, OLD, 1000)
        s = mc.snapshot(gold, self.uc)
        self.assertEqual((s["bundle_id"], s["data_mib"], s["stale"]), (mc.LICHII_ID, 4, False))
        self.assertIsNone(mc.expect_cold(s))
        self.assertEqual(mc.expect_cold(s, spec_cold=True), "empty Metal cache (cold_metal_cache)")
        make_cache(self.uc, mc.LICHII_ID + ".nuptest", NEW, 2000)
        self.assertEqual(mc.expect_cold(mc.snapshot(gold, self.uc)), "Metal cache reset (macOS update)")


class Verdict(unittest.TestCase):
    warm = {"stamps": NEW, "data_mib": 400, "stale": False}

    def test_warm(self):
        self.assertEqual(mc.verdict(self.warm, self.warm, 12), {"cold": False, "reasons": []})
        self.assertFalse(mc.verdict(self.warm, self.warm, None)["cold"])  # the log could not be read

    def test_stamp_changed_during_the_run(self):
        before = dict(self.warm, stamps=OLD)
        v = mc.verdict(before, self.warm, 12454)
        self.assertTrue(v["cold"])
        self.assertEqual(v["reasons"], ["Metal cache reset (macOS update)", "12,454 shaders compiled during boot and load"])

    def test_known_stale_is_named_once(self):
        before = dict(self.warm, stamps=OLD, stale=True)
        self.assertEqual(mc.verdict(before, self.warm, None)["reasons"], ["Metal cache reset (macOS update)"])

    def test_many_compiles_alone(self):
        v = mc.verdict(self.warm, self.warm, mc.COLD_REQUESTS + 1)
        self.assertTrue(v["cold"]); self.assertEqual(len(v["reasons"]), 1)


class Log(unittest.TestCase):
    def line(self, parent, msg="Compilation BEGIN"):
        return json.dumps({"eventMessage": f"{msg} (ParentProcessName={parent}) Build request: MTLBuildOpaqueRequest - opaque"})

    def test_counts_only_this_process(self):
        lines = [self.line("lichii_1234")] * 3 + [self.line("lichii_12345"), self.line("bench_1234"),
                                                  self.line("lichii_1234", "Compilation END"), "not json lichii_1234",
                                                  "[{", ""]
        self.assertEqual(mc.count_requests(lines, "lichii_1234"), 3)
        self.assertEqual(mc.count_requests(lines, "lichii_12345"), 1)
        self.assertEqual(mc.count_requests([], "lichii_1"), 0)


class PipelineBoot(unittest.TestCase):
    built = "LoadPipelinesV2: Total Pipeline Count: 14950\nx\nLoadPipelinesV2: Shader cache v2 boot load: 423.6 s, " \
            "876 of 876 compute and 14074 of 14074 graphics pipelines built (the used list)\n"
    skipped = "LoadDiskResources: Shader cache v2: the last boot ended while building cached pipelines; building " \
              "none at boot this time\nLoadPipelinesV2: Total Pipeline Count: 0\nLoadPipelinesV2: Shader cache v2 " \
              "boot load: 0.7 s, 0 of 0 compute and 0 of 0 graphics pipelines built\n"

    def test_built(self):
        self.assertEqual(mc.pipeline_boot(self.built), {"in_file": 14950, "built": 14950, "skipped": False})

    def test_skipped_after_an_interrupted_boot(self):
        self.assertEqual(mc.pipeline_boot(self.skipped), {"in_file": 0, "built": 0, "skipped": True})

    def test_no_such_lines(self):
        self.assertEqual(mc.pipeline_boot("nothing"), {"in_file": None, "built": None, "skipped": False})

    def test_recorded_runs(self):
        logs = sorted((HARNESS / "runs").glob("ab-*/*/eden_log.txt"))[-150:]
        if not logs:
            self.skipTest("no recorded runs on this machine (tools/harness/runs is local data)")
        seen = {"built": 0, "skipped": 0}
        for log in logs:
            b = mc.pipeline_boot(log.read_text(errors="replace"))
            if b["skipped"]:
                seen["skipped"] += 1; self.assertIn(b["built"], (0, None), log)
            elif b["in_file"] and b["built"] is not None:
                seen["built"] += 1; self.assertLessEqual(b["built"], b["in_file"], log)   # some boots build only the used ones
        self.assertGreater(seen["built"], 0)
        print(f"({len(logs)} recorded logs: {seen['built']} built their pipelines, {seen['skipped']} skipped them) ",
              end="", file=sys.stderr)


class Progress(unittest.TestCase):
    def test_made_up_tail(self):
        tail = "x (12 mesh shaders so far)\npipeline cache load 3900 libraries, 40%\n(57 mesh shaders so far)\n" \
               "pipeline cache load 14950 libraries, 85%\n"
        self.assertEqual(mc.progress_text(tail), ["57 mesh", "pipeline cache 85% (14,950 libraries)"])
        self.assertEqual(mc.progress_text("nothing here"), [])

    def test_recorded_runs(self):
        """Every recorded boot's stderr parses, and where it reports the pipeline file's load, the text says so."""
        logs = sorted((HARNESS / "runs").glob("ab-*/*/stderr.log"))
        if not logs:
            self.skipTest("no recorded runs on this machine (tools/harness/runs is local data)")
        seen = 0
        for log in logs:
            text = log.read_bytes().decode(errors="replace")
            parts = mc.progress_text(text)
            if "pipeline cache load" in text and " libraries, " in text:
                seen += 1
                self.assertTrue(any(p.startswith("pipeline cache ") and p.endswith("libraries)") for p in parts), log)
            if "mesh shaders so far)" in text:
                self.assertTrue(any(p.endswith(" mesh") for p in parts), log)
        print(f"({len(logs)} recorded stderr logs read, {seen} with a pipeline-file load) ", end="", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
