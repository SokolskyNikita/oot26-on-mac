#!/bin/sh
# phase2.sh: value-taking arguments, private pipeline settings and option properties: timing; then GPU code size for all.
cd "$(dirname "$0")"; export MTL_SHADER_CACHE_SIZE=0; f=v-slim.metal
./probe valcand.txt > val-probe.txt 2>&1
awk -F'\t' '$1=="OK"{print $2}' val-probe.txt > val-ok.txt
t() { label="$1"; shift; ./bench -reps 3 "$@" $f 2>&1 | awk -v a="$label" '/^v-slim.* lib=/{ split($3,l,"="); split($4,p,"="); if (bl==""||l[2]+0<bl) bl=l[2]+0; if (bp==""||p[2]+0<bp) bp=p[2]+0; k++ } /FAIL/{f++} END{ printf "%s\t%s\t%s\t%d\t%d\n", a, bl, bp, k, f }'; }
n=0; base() { [ $((n % 30)) -eq 0 ] && t BASELINE; n=$((n+1)); }
{
while IFS= read -r a; do base; t "arg $a" -args "$a"; done < val-ok.txt
while IFS= read -r k; do base; t "driverCompilerOptions $k=true" -pipekv "driverCompilerOptions:$k=true"; t "gpuCompilerSPIOptions $k=true" -pipekv "gpuCompilerSPIOptions:$k=true"; done < pipekeys-all.txt
for p in tracingEnabled debuggingEnabled compileTimeStatisticsEnabled enableLogging framebufferReadEnabled allowReferencingUndefinedSymbols preserveInvariance; do base; t "option $p=true" -kv "$p=true"; done
for v in 0 1 2; do t "option sourceLanguage=$v" -kv "sourceLanguage=$v"; t "option compileSymbolVisibility=$v" -kv "compileSymbolVisibility=$v"; t "option floatingPointConversionRoundingMode=$v" -kv "floatingPointConversionRoundingMode=$v"; done
t "pipeline compilerTimeoutInSeconds=1" -pipekv "self:compilerTimeoutInSeconds=1"
t BASELINE
} > phase2-time.tsv 2> phase2-time.err
sz() { label="$1"; shift; rm -f ar.bin; ./bench -q "$@" -archive ar.bin $f > /dev/null 2>&1; if [ -f ar.bin ]; then printf "%s\t%s\n" "$label" "$(python3 gpusize.py ar.bin)"; else printf "%s\tFAIL\n" "$label"; fi; }
{
sz BASELINE
while IFS= read -r a; do sz "arg $a" -args "$a"; done < ok.txt
while IFS= read -r a; do sz "arg $a" -args "$a"; done < val-ok.txt
for a in "-O0" "-O1" "-O2" "-O3" "-Os" "-Oz" "-Og" "-Ofast"; do sz "arg $a" -args "$a"; done
while IFS= read -r k; do sz "driverCompilerOptions $k=true" -pipekv "driverCompilerOptions:$k=true"; sz "gpuCompilerSPIOptions $k=true" -pipekv "gpuCompilerSPIOptions:$k=true"; done < pipekeys-all.txt
sz BASELINE
} > phase2-size.tsv 2> phase2-size.err
wc -l val-ok.txt phase2-time.tsv phase2-size.tsv
