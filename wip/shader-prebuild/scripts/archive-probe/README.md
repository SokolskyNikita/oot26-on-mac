# MTLBinaryArchive probes

Standalone; nothing here touches Lichii or MoltenVK. Results are in `../../binary-archives.md`.

- `batest.swift`: `batest <mode> <seed> <dir>`. Modes `make` (compile, add to an archive, serialise), `noarch`
  (control), `arch` (strict lookup from the archive in a new process), plus `dup`, `addfunc`, `fileonly`,
  `bytesonly`, `fromfile` as used in the write-up. `NSTMT` sets the fragment shader's length. Build with
  `swiftc -O batest.swift -o batest`; run with `MTL_SHADER_CACHE_SIZE=0` so Metal's own cache does not answer.
- `pathtest.swift`: checks which cache folders `MTLSetShaderCachePath` moves (shader and module caches, not
  `com.apple.gpuarchiver`).
- `extract_msl.py`, `extract_spv.py`: pull the MSL or SPIR-V of real game shaders out of Lichii/MoltenVK cache
  files, as input for the scale probe (step 1 of the plan). `python3 -I extract_msl.py OUTDIR BLOB...`.
- `Info.plist`: bundle id `local.ba-scale-probe` for the scale probe app, so its Metal cache folder is its own.
