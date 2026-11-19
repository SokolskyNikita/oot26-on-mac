#!/usr/bin/env python3
"""make-final.py OUTDIR: the finished Hypervisor change as patched copies of three Lichii files and one patch.

Starts from the pristine files in path-60/lichii, applies the speed experiments of 2026-11-17 and the two
render-race patches, then makes the edits that finish the work:

- memory.cpp / memory.h: the protection of a region being cached moves into Memory::Impl::ProtectForCaching, and
  Memory::ReprotectIfCached(page) puts a cached page's protection back.
- arm_hvf.cpp: after the fault handler gives a page its kernel permissions back, it asks ReprotectIfCached. With
  pages marked before they are protected, every order of the two threads now ends with a cached page protected.
- arm_hvf.cpp, opt-in and NOT verified: with EDEN_NX2_HVF_INTERPRET_READS=1 a load from a GPU-cached page is
  interpreted every time instead of the page being opened for reading after its first read (the suspected cause
  of the blown-out and rainbow pictures in about one Hypervisor boot in ten).
- arm_hvf.cpp: the loop runner (256 instructions) and dirty-only write-back are on by default; EDEN_NX2_HVF_LOOP,
  EDEN_NX2_HVF_BURST and EDEN_NX2_HVF_DIRTY_ONLY still override them.

Writes OUTDIR/src/... (the patched files) and OUTDIR/hvf-final.patch (against the pristine files)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
P60 = Path(os.environ.get("P60", "OLD_REPO/emulator/mvk-mesh/path-60"))
SRC = P60 / "lichii"
SPEED = P60.parent.parent / "debugsrv/patches/hvf-experiments-2026-11-17.patch"
RACE = HERE.parent.parent / "investigations/hypervisor-render-bug"
FILES = ["src/core/arm/hvf/arm_hvf.cpp", "src/core/memory.cpp", "src/core/memory.h"]
LOOP_DEFAULT = int(os.environ.get("LOOP_DEFAULT", "256"))


def sub(text, old, new, count=1):
    assert text.count(old) == count, f"expected {count} of {old[:60]!r}, found {text.count(old)}"
    return text.replace(old, new)


def main(out):
    out = Path(out)
    for tree in ("a", "b"):
        shutil.rmtree(out / tree, ignore_errors=True)
        for f in FILES:
            (out / tree / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SRC / f, out / tree / f)
    for p in (SPEED, RACE / "01-count-dropped-protection.patch", RACE / "02-mark-before-protect.patch"):
        subprocess.run(["patch", "-s", "-p1", "-i", str(p)], cwd=out / "b", check=True)

    # ---- memory.cpp ----
    p = out / "b/src/core/memory.cpp"; s = p.read_text()
    a = s.index("        // When a region becomes cached its pages are marked before they are protected.")
    b = s.index("        if (!cached) {\n            protect();\n        }\n")
    lam = s[a:b]
    body = lam[lam.index("            if (!current_page_table->fastmem_arena) {"):lam.rindex("        };")]
    body = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines()) + "\n"
    s = s[:a] + ("        // When a region becomes cached its pages are marked before they are protected. A fault on a\n"
                 "        // protected page then finds it marked, or the Hypervisor fault handler's ReprotectIfCached\n"
                 "        // does: a cached page must never be left writable, or its writes go unseen by the GPU's\n"
                 "        // caches.\n") + s[b:]
    # The loop between the two calls advances vaddr page by page, so the region's start is kept in a constant
    # (the lambda this replaces had captured vaddr by value before the loop).
    s = sub(s, "        if (!cached) {\n            protect();\n        }\n",
            "        const u64 region_start = vaddr;\n"
            "        if (!cached) {\n            ProtectForCaching(region_start, size, cached);\n        }\n")
    s = sub(s, "        if (cached) {\n            protect();\n        }\n",
            "        if (cached) {\n            ProtectForCaching(region_start, size, cached);\n        }\n")
    member = ("    /// The guest protection of a region that is becoming cached (no writes; no reads either under reactive\n"
              "    /// flushing or an armed read trap) or uncached (everything allowed).\n"
              "    void ProtectForCaching(u64 vaddr, u64 size, bool cached) {\n" + body + "    }\n\n"
              "    /// For the Hypervisor fault handler, after it gave a page its kernel permissions back: if the GPU\n"
              "    /// thread has marked the page as cached meanwhile, protect it again. True when it did.\n"
              "    bool ReprotectIfCached(u64 vaddr) {\n"
              "        const u64 page = vaddr >> LICHII_PAGEBITS;\n"
              "        if (!AddressSpaceContains(*current_page_table, vaddr, 1) ||\n"
              "            std::as_const(current_page_table->entries)[page].Type() !=\n"
              "                Common::PageType::RasterizerCachedMemory) {\n"
              "            return false;\n"
              "        }\n"
              "        ProtectForCaching(page << LICHII_PAGEBITS, LICHII_PAGESIZE, true);\n"
              "        return true;\n"
              "    }\n\n")
    s = sub(s, "    void RasterizerMarkRegionCached(u64 vaddr, u64 size, bool cached) {\n",
            member + "    void RasterizerMarkRegionCached(u64 vaddr, u64 size, bool cached) {\n")
    s = sub(s, "bool Memory::GrantCachedPageRead(Common::ProcessAddress vaddr, u64 expected_token) {\n",
            "bool Memory::ReprotectIfCached(Common::ProcessAddress vaddr) {\n"
            "    return impl->ReprotectIfCached(GetInteger(vaddr));\n}\n\n"
            "bool Memory::GrantCachedPageRead(Common::ProcessAddress vaddr, u64 expected_token) {\n")
    p.write_text(s)

    # ---- memory.h ----
    p = out / "b/src/core/memory.h"; s = p.read_text()
    s = sub(s, "    bool GrantCachedPageRead(Common::ProcessAddress vaddr, u64 expected_token);\n",
            "    bool GrantCachedPageRead(Common::ProcessAddress vaddr, u64 expected_token);\n\n"
            "    /// Protects the page again if it is GPU-cached. For the Hypervisor fault handler, after it gave a\n"
            "    /// page its kernel permissions back: the GPU thread may have cached the page meanwhile.\n"
            "    bool ReprotectIfCached(Common::ProcessAddress vaddr);\n")
    p.write_text(s)

    # ---- arm_hvf.cpp ----
    p = out / "b/src/core/arm/hvf/arm_hvf.cpp"; s = p.read_text()
    a = s.index("                // Diagnostic: the GPU thread protects a region before it marks its pages cached")
    b = s.index("                return retry();", a)
    s = s[:a] + (
        "                // The GPU thread may be caching this page right now. It marks a page before it protects\n"
        "                // it, so a page that is marked here is protected again; one that is marked later is\n"
        "                // protected by the GPU thread after this. Either way no cached page stays writable.\n"
        "                if (m_memory.ReprotectIfCached(page_address)) {\n"
        "                    static std::atomic<u64> reprotected{};\n"
        "                    const u64 count = reprotected.fetch_add(1, std::memory_order_relaxed) + 1;\n"
        "                    if (count <= 8 || count % 1000 == 0) {\n"
        "                        LOG_INFO(Core_ARM,\n"
        "                                 \"Page {:#x} became GPU-cached while its protection was being lifted: \"\n"
        "                                 \"protected again (#{}, {} at pc {:#x})\",\n"
        "                                 page_address, count, write ? \"write\" : \"read\", pc);\n"
        "                    }\n"
        "                }\n") + s[b:]
    s = sub(s, "    std::atomic<u32> burst{0}, loop{0};\n    std::atomic<bool> dirty_only{false}, raw_counter{false};\n",
            f"    std::atomic<u32> burst{{0}}, loop{{{LOOP_DEFAULT}}};\n"
            "    std::atomic<bool> dirty_only{true}, raw_counter{false};\n")
    s = sub(s, '        dirty_only = HvfFlag("EDEN_NX2_HVF_DIRTY_ONLY");\n',
            '        if (const char* v = std::getenv("EDEN_NX2_HVF_DIRTY_ONLY")) {\n'
            "            dirty_only = v[0] == '1';\n        }\n")
    s = sub(s, "// Experiments (2026-11-17, ocarina emulator/debugsrv): each off unless its variable is set.\n",
            "// Speed switches (2026-11-17, ocarina emulator/debugsrv). The loop runner and dirty-only write-back are\n"
            f"// on by default (EDEN_NX2_HVF_LOOP={LOOP_DEFAULT}, EDEN_NX2_HVF_DIRTY_ONLY=1); the others are off unless set.\n"
            "//   EDEN_NX2_HVF_LOOP=N        run up to N following instructions of a fill or copy loop per exit (0 = off)\n")
    # Reads of GPU-cached pages under reactive flushing: interpret each load instead of opening the page.
    s = sub(s, "    if (access == Access::Denied && m_fault_repeats < 3) {\n        if (!write) {\n",
            "    // With reactive flushing (the default) a cached page has no read permission and nothing takes it away\n"
            "    // again once it is given: read traps, which re-arm on a GPU write, are off in that mode. Opening the\n"
            "    // page after its first read (below) would let every later read see the guest copy without asking the\n"
            "    // GPU, the same as reactive flushing off: stale read-backs, seen as a blown-out or rainbow picture in\n"
            "    // about one boot in ten. So each load goes through the emulator's memory, as Dynarmic's slow path\n"
            "    // does. NOT VERIFIED YET (2026-11-18): the change is off unless EDEN_NX2_HVF_INTERPRET_READS=1, so\n"
            "    // the default is the behaviour that was measured.\n"
            "    static const bool interpret_reads = HvfFlag(\"EDEN_NX2_HVF_INTERPRET_READS\");\n"
            "    if (!write && gpu_cached && interpret_reads && !m_memory.ReadTrapsEnabled() &&\n"
            "        InterpretAccess(vcpu, m_memory)) {\n"
            "        g_stats.Count(g_stats.read_interpreted);\n"
            "        m_fault_repeats = 0;\n"
            "        return {};\n"
            "    }\n\n"
            "    if (access == Access::Denied && m_fault_repeats < 3) {\n        if (!write) {\n")
    s = sub(s, "    std::atomic<u64> svc, system_register, stale_tlb, read_fault, write_fault, interpreted,\n        invalidated;\n",
            "    std::atomic<u64> svc, system_register, stale_tlb, read_fault, write_fault, interpreted,\n"
            "        invalidated, read_interpreted;\n")
    s = sub(s, '"faults, {} write faults ({} interpreted, {} invalidated the GPU\'s caches)",\n',
            '"faults ({} interpreted), {} write faults ({} interpreted, {} invalidated the GPU\'s caches)",\n')
    s = sub(s, "rate(svc), rate(system_register), rate(stale_tlb), rate(read_fault),\n",
            "rate(svc), rate(system_register), rate(stale_tlb), rate(read_fault), rate(read_interpreted),\n")
    p.write_text(s)

    p = out / "b/src/core/memory.cpp"; s = p.read_text()
    s = sub(s, "bool Memory::ReprotectIfCached(Common::ProcessAddress vaddr) {\n",
            "bool Memory::ReadTrapsEnabled() const {\n    return impl->ReadTrapsEnabled();\n}\n\n"
            "bool Memory::ReprotectIfCached(Common::ProcessAddress vaddr) {\n")
    p.write_text(s)
    p = out / "b/src/core/memory.h"; s = p.read_text()
    s = sub(s, "    bool ReprotectIfCached(Common::ProcessAddress vaddr);\n",
            "    bool ReprotectIfCached(Common::ProcessAddress vaddr);\n\n"
            "    /// Whether GPU writes re-arm read protection page by page (off under reactive flushing, where a\n"
            "    /// cached page simply has no read permission).\n"
            "    bool ReadTrapsEnabled() const;\n")
    p.write_text(s)

    diff = subprocess.run(["diff", "-ru", "a", "b"], cwd=out, capture_output=True, text=True).stdout
    (out / "hvf-final.patch").write_text(diff)
    print(f"{out}/hvf-final.patch: {len(diff.splitlines())} lines; loop default {LOOP_DEFAULT}")


if __name__ == "__main__":
    main(sys.argv[1])
