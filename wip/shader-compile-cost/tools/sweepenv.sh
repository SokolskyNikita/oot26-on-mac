#!/bin/sh
# sweepenv.sh: time one shader with each environment name set to 1 and to 0; a baseline row every 30 names.
# Run from a scratch folder (some switches write files into the current directory).
S="$1"; export MTL_SHADER_CACHE_SIZE=0; f=$S/v-slim.metal; n=0
one() { env $2 $S/bench -reps 3 $f 2>&1 | awk -v a="$1" '/^v-slim.* lib=/{ split($3,l,"="); split($4,p,"="); if (bl==""||l[2]+0<bl) bl=l[2]+0; if (bp==""||p[2]+0<bp) bp=p[2]+0; k++ } /FAIL/{f++} END{ printf "%s\t%s\t%s\t%d\t%d\n", a, bl, bp, k, f }'; }
while IFS= read -r e; do
  [ $((n % 30)) -eq 0 ] && one BASELINE "X_UNUSED=1"
  one "$e=1" "$e=1"; one "$e=0" "$e=0"; n=$((n+1))
done < $S/envnames.txt
one BASELINE "X_UNUSED=1"
