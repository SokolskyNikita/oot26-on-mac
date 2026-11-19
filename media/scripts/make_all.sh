#!/bin/sh
# Regenerate every picture in media/. Run from anywhere; needs uv.
# The walk chart and the specks pair read local run data under tools/harness/runs/ (not tracked), and the canopy pair
# reads two screenshots in data/; those steps are skipped with a message when the data is missing.
set -eu
cd "$(dirname "$0")/.."
PY="uv run -q --with matplotlib --with numpy --with pillow python"
RUNS=../tools/harness/runs
SHOTS=../research/mac-performance/shots

$PY scripts/frame_time_steps.py data/frame-time-steps.csv frame-time-steps.png
$PY scripts/boot_times.py data/boot-times.csv boot-times.png

if [ -d "$RUNS/ab-20261118-014956/merge-gold-1" ] && [ -d "$RUNS/ab-20261118-014956/merge-512-2" ]; then
  $PY scripts/walk_frame_times.py "$RUNS/ab-20261118-014956/merge-gold-1" "$RUNS/ab-20261118-014956/merge-512-2" \
    walk-frame-times.png
else
  echo "skip walk-frame-times.png: run ab-20261118-014956 not found" >&2
fi

SB="Build before the fix, mesh shaders native (MoltenVK PR #2842): mesh draws inherit the previous draw's cull mode. 7 of 8 frames speckled in this burst."
SA="Build with the cull-mode fix (the pinned build's MoltenVK): each mesh pipeline applies its own cull mode. 0 of 30 frames speckled."
BEFORE="$RUNS/ab-20261117-220023/specks-counter-native/before"
AFTER="$RUNS/ab-20261118-000338/wall-practice-rolled-out/wall"
if [ -d "$BEFORE" ] && [ -d "$AFTER" ]; then
  $PY scripts/pair.py "$BEFORE/f000.png" "$AFTER/f000.png" specks-before-after.png \
    --title "White specks on the Kokiri cave wall: mesh cull-mode fix" --before-label "$SB" --after-label "$SA" \
    --note "Same spot, Link stopped at the cave wall. First frame of each burst, game area only. Runs ab-20261117-220023 / specks-counter-native and ab-20261118-000338 / wall-practice-rolled-out (local run data, not tracked)."
  $PY scripts/pair.py "$BEFORE" "$AFTER" specks-before-after.gif \
    --title "White specks on the Kokiri cave wall: mesh cull-mode fix" --before-label "$SB" --after-label "$SA" \
    --note "First 8 frames of each burst, 0.35 s per frame (not real time). Runs ab-20261117-220023 / specks-counter-native and ab-20261118-000338 / wall-practice-rolled-out (local run data)." \
    --gif-frames 8 --gif-width 1000
else
  echo "skip specks-before-after: burst folders not found" >&2
fi

$PY scripts/pair.py "$SHOTS/native-mesh-no-position-fix.png" "$SHOTS/native-mesh-with-position-fix.png" \
  mesh-position-before-after.png \
  --title "Upside-down foliage with native mesh shaders: mesh position fix" \
  --before-label "Native mesh shaders without the fix: SPIRV-Cross skips the Y flip and depth fixup for a standalone mesh position, so foliage is drawn upside down in the sky and the ground grass is missing." \
  --after-label "With the two added lines in the generated Metal source (Y flip and depth fixup): the picture matches stock at the spawn." \
  --note "Kokiri Forest spawn, 2026-11-16, game area only. Images: research/mac-performance/shots/native-mesh-no-position-fix.png and native-mesh-with-position-fix.png (research/mac-performance/README.md, cause 4.3)."

if [ -f data/base-5189f8d.standing.jpg ] && [ -f data/push16.standing.jpg ]; then
  $PY scripts/pair.py data/base-5189f8d.standing.jpg data/push16.standing.jpg \
    canopy-before-after.png \
    --title "Missing tree canopy on MoltenVK main: maxPushDescriptors capped at 16" \
    --before-label "MoltenVK main reports maxPushDescriptors 287; Lichii pushes 37-buffer sets past Metal's 31 slots, 5 compute pipelines fail and the canopy is bare." \
    --after-label "Reported as 16 (as Lichii's bundled MoltenVK fork does): all 135 compute pipelines build and the canopy is leafy." \
    --note "Kokiri Forest spawn, Lichii nx2 7c7f723 with MoltenVK main of 2026-10-13; the white specks in the after picture are a separate fault. Images: media/data/, runs base and push16 in research/compute-buffer-bounds/README.md."
else
  echo "skip canopy-before-after.png: media/data/ images not found" >&2
fi

$PY scripts/pair.py "$SHOTS/stock-228.png" "$SHOTS/all-in-one.png" stock-vs-combined.png \
  --title "Stock Lichii build 228 against the first combined build (all-in-one)" \
  --before-label "Stock release 228 with its bundled MoltenVK, mesh shaders emulated: 39.4–39.6 ms standing." \
  --after-label "All-in-one (Lichii patches 0001–0005, MoltenVK patches 0001–0005, native mesh shaders): 27.9–29.2 ms standing. Picture matches stock by eye." \
  --note "Kokiri Forest spawn, 2026-11-16, game area only; frame times from research/mac-performance/README.md (Results, rows 0 and 2, harness V). Images: research/mac-performance/shots/stock-228.png and all-in-one.png."
