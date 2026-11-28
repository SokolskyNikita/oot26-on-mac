#!/bin/sh
# sweepargs.sh: time every argument in ok.txt (one per line) on v-slim.metal with ./bench; a baseline row every 40.
# Run from a folder holding the built bench, the shader and the list. Output: argument, best front end ms, best back end ms, runs, failures.
export MTL_SHADER_CACHE_SIZE=0
f=v-slim.metal; n=0
one() { ./bench -reps 3 -args "$1" $f 2>&1 | awk -v a="$1" '/^v-slim.* lib=/{ split($3,l,"="); split($4,p,"="); if (bl==""||l[2]+0<bl) bl=l[2]+0; if (bp==""||p[2]+0<bp) bp=p[2]+0; k++ } /FAIL/{f++} END{ printf "%s\t%s\t%s\t%d\t%d\n", a, bl, bp, k, f }'; }
while IFS= read -r a; do
  [ $((n % 40)) -eq 0 ] && one "-O2" | sed 's/^-O2/BASELINE/'
  one "$a"; n=$((n+1))
done < ok.txt
one "-O2" | sed 's/^-O2/BASELINE/'
