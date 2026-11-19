// Differential test of the load/store interpreter the Hypervisor backend uses for faulting
// accesses (InterpretAccess in src/core/arm/hvf/arm_hvf.cpp).
//
// Each test instruction runs twice from the same registers and memory: once on this Mac's CPU,
// once through the interpreter. Registers and memory must match afterwards.
//
// - The general loads and stores are tested through the emulator's own built object
//   (interpreter_visitor.cpp.o), linked in as is.
// - DC ZVA and the single-element ST1/LD1 live inside arm_hvf.cpp between Hypervisor.framework
//   calls, so they are tested through a copy of that code (SpecialCase below). Keep it in step
//   with the source.

#include <array>
#include <csetjmp>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <optional>
#include <random>
#include <span>

#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>

using u8 = uint8_t;
using u32 = uint32_t;
using u64 = uint64_t;
using u128 = std::array<u64, 2>;

struct State {
    u64 x[31];
    u64 sp;
    u128 v[32];
    u64 host_sp;
    u64 pad;
};
static_assert(offsetof(State, sp) == 248 && offsetof(State, v) == 256 &&
              offsetof(State, host_sp) == 768);

// ---- Guest memory: one buffer, addressed by its host address. ----

constexpr size_t MemSize = 1 << 16;
alignas(4096) static u8 g_mem[MemSize];
static bool g_out_of_bounds;
static u32 g_instruction;
static u64 g_instruction_pc;

static bool InBounds(u64 address, size_t size) {
    const u64 base = reinterpret_cast<u64>(g_mem);
    return address >= base && size <= MemSize && address - base <= MemSize - size;
}

// The three Core::Memory::Memory members the interpreter object calls.
extern "C" {
bool StubReadBlock(void*, u64 address, void* dest, size_t size) asm(
    "__ZN4Core6Memory6Memory9ReadBlockEN6Common12TypedAddressILb1ENS2_17ProcessAddressTagEEEPvm");
bool StubWriteBlock(void*, u64 address, const void* src, size_t size) asm(
    "__ZN4Core6Memory6Memory10WriteBlockEN6Common12TypedAddressILb1ENS2_17ProcessAddressTagEEEPKvm");
u32 StubRead32(void*, u64 address) asm(
    "__ZN4Core6Memory6Memory6Read32EN6Common12TypedAddressILb1ENS2_17ProcessAddressTagEEE");
void StubAssertFatal() asm("__Z15AssertFatalImplv");
void StubAssertSoft() asm("__Z18AssertFailSoftImplv");
void StubLog() asm(
    "__ZN6Common3Log17FmtLogMessageImplENS0_5ClassENS0_5LevelEPKcjS4_N3fmt3v1217basic_string_"
    "viewIcEERKNS6_17basic_format_argsINS6_7contextEEE");
}

bool StubReadBlock(void*, u64 address, void* dest, size_t size) {
    if (!InBounds(address, size)) {
        g_out_of_bounds = true;
        std::memset(dest, 0, size);
        return false;
    }
    std::memcpy(dest, reinterpret_cast<void*>(address), size);
    return true;
}
bool StubWriteBlock(void*, u64 address, const void* src, size_t size) {
    if (!InBounds(address, size)) {
        g_out_of_bounds = true;
        return false;
    }
    std::memcpy(reinterpret_cast<void*>(address), src, size);
    return true;
}
u32 StubRead32(void*, u64 address) {
    return address == g_instruction_pc ? g_instruction : 0;
}
static bool g_assert_hit;
void StubAssertFatal() {
    g_assert_hit = true;
}
void StubAssertSoft() {
    g_assert_hit = true;
}
void StubLog() {}

namespace Core {
std::optional<u64> MatchAndExecuteOneInstruction(void* memory, std::span<u64, 31> regs,
                                                 std::span<u128, 32> vregs, u64& sp,
                                                 const u64& pc) asm(
    "__ZN4Core29MatchAndExecuteOneInstructionERNS_6Memory6MemoryENSt3__14spanIyLm31EEENS4_INS3_"
    "5arrayIyLm2EEELm32EEERyRKy");
}

// ---- Copy of the two special cases at the top of InterpretAccess. ----

static bool SpecialCase(State& s, u32 instruction) {
    // DC ZVA, Xt
    if ((instruction & 0xFFFFFFE0) == 0xD50B7420) {
        const u32 rt = instruction & 0x1F;
        const u64 address = rt == 31 ? 0 : s.x[rt];
        const u64 block = address & ~u64{63};
        if (!InBounds(block, 64)) {
            g_out_of_bounds = true;
            return true;
        }
        std::memset(reinterpret_cast<void*>(block), 0, 64);
        return true;
    }
    // ST1/LD1 of one vector element
    if ((instruction & 0xBF000000) == 0x0D000000) {
        const bool post_index = (instruction & (1U << 23)) != 0;
        const bool load = (instruction & (1U << 22)) != 0;
        const bool pair = (instruction & (1U << 21)) != 0;
        const u32 rm = (instruction >> 16) & 0x1F;
        const u32 opcode = (instruction >> 13) & 0x7;
        const u32 s_bit = (instruction >> 12) & 1;
        const u32 size = (instruction >> 10) & 0x3;
        const u32 rn = (instruction >> 5) & 0x1F;
        const u32 rt = instruction & 0x1F;
        const u32 q = (instruction >> 30) & 1;
        u32 scale = opcode >> 1;
        u32 index = (q << 3) | (s_bit << 2) | size;
        bool valid = !pair && (opcode & 1) == 0 && scale != 3 && (post_index || rm == 0);
        if (scale == 1) {
            valid = valid && (size & 1) == 0;
            index >>= 1;
        } else if (scale == 2) {
            if ((size & 1) == 0) {
                valid = valid && (size & 2) == 0;
                index >>= 2;
            } else {
                valid = valid && s_bit == 0 && size == 1;
                index = q;
                scale = 3;
            }
        }
        if (valid) {
            const u32 bytes = 1U << scale;
            const u64 address = rn == 31 ? s.sp : s.x[rn];
            u8* const element = reinterpret_cast<u8*>(&s.v[rt]) + index * bytes;
            if (load) {
                StubReadBlock(nullptr, address, element, bytes);
            } else {
                StubWriteBlock(nullptr, address, element, bytes);
            }
            if (post_index) {
                const u64 offset = rm == 31 ? bytes : s.x[rm];
                if (rn == 31) {
                    s.sp = address + offset;
                } else {
                    s.x[rn] = address + offset;
                }
            }
            return true;
        }
    }
    return false;
}

static bool Interpret(State& s, u32 instruction, bool& special) {
    special = SpecialCase(s, instruction);
    if (special) {
        return true;
    }
    g_instruction = instruction;
    g_instruction_pc = 0x1000;
    const u64 pc = g_instruction_pc;
    const auto next = Core::MatchAndExecuteOneInstruction(
        nullptr, std::span<u64, 31>{s.x, 31}, std::span<u128, 32>{s.v, 32}, s.sp, pc);
    return next.has_value();
}

// ---- Native execution. ----

extern "C" {
extern const u8 tramp_a_start[], tramp_a_slot[], tramp_a_end[];
extern const u8 tramp_b_start[], tramp_b_slot[], tramp_b_end[];
}

static u8* g_jit;
static sigjmp_buf g_jump;
static volatile sig_atomic_t g_in_native;
static u64 g_saved_host_sp;

static void OnFault(int signal) {
    if (!g_in_native) {
        _exit(100 + signal);
    }
    siglongjmp(g_jump, signal);
}

struct Tramp {
    void (*entry)(State*);
    u32* slot;
};
static Tramp g_tramp_a, g_tramp_b;

static Tramp Install(u8* at, const u8* start, const u8* slot, const u8* end) {
    std::memcpy(at, start, static_cast<size_t>(end - start));
    return {reinterpret_cast<void (*)(State*)>(at), reinterpret_cast<u32*>(at + (slot - start))};
}

/// 0 when the instruction ran, else the signal it raised.
static int RunNative(const Tramp& tramp, State& s, u32 instruction) {
    pthread_jit_write_protect_np(0);
    *tramp.slot = instruction;
    pthread_jit_write_protect_np(1);
    sys_icache_invalidate(tramp.slot, 4);
    g_in_native = 1;
    const int signal = sigsetjmp(g_jump, 1);
    if (signal == 0) {
        tramp.entry(&s);
    }
    g_in_native = 0;
    return signal;
}

// ---- The test loop. ----

static bool SameState(const State& a, const State& b, bool with_sp) {
    return std::memcmp(a.x, b.x, sizeof(a.x)) == 0 && std::memcmp(a.v, b.v, sizeof(a.v)) == 0 &&
           (!with_sp || a.sp == b.sp);
}

static void Describe(const char* what, u32 instruction, const State& before, const State& interp,
                     const State& native, const u8* mem_interp, const u8* mem_native,
                     bool with_sp) {
    std::printf("MISMATCH (%s): instruction %08X\n", what, instruction);
    for (int i = 0; i < 31; ++i) {
        if (interp.x[i] != native.x[i]) {
            std::printf("  x%d: before %016llx, interpreter %016llx, native %016llx\n", i,
                        before.x[i], interp.x[i], native.x[i]);
        }
    }
    if (with_sp && interp.sp != native.sp) {
        std::printf("  sp: before %016llx, interpreter %016llx, native %016llx\n", before.sp,
                    interp.sp, native.sp);
    }
    for (int i = 0; i < 32; ++i) {
        if (interp.v[i] != native.v[i]) {
            std::printf("  v%d: before %016llx%016llx, interpreter %016llx%016llx, native "
                        "%016llx%016llx\n",
                        i, before.v[i][1], before.v[i][0], interp.v[i][1], interp.v[i][0],
                        native.v[i][1], native.v[i][0]);
        }
    }
    int shown = 0;
    for (size_t i = 0; i < MemSize && shown < 24; ++i) {
        if (mem_interp[i] != mem_native[i]) {
            std::printf("  mem+%#zx: interpreter %02x, native %02x\n", i, mem_interp[i],
                        mem_native[i]);
            ++shown;
        }
    }
}

enum class Kind { General, St1Single, DcZva };

int main(int argc, char** argv) {
    const u64 iterations = argc > 1 ? std::strtoull(argv[1], nullptr, 0) : 2'000'000;
    const u64 seed = argc > 2 ? std::strtoull(argv[2], nullptr, 0) : 1;
    std::mt19937_64 rng{seed};

    g_jit = static_cast<u8*>(mmap(nullptr, 0x4000, PROT_READ | PROT_WRITE | PROT_EXEC,
                                  MAP_PRIVATE | MAP_ANON | MAP_JIT, -1, 0));
    if (g_jit == MAP_FAILED) {
        std::perror("mmap MAP_JIT");
        return 2;
    }
    pthread_jit_write_protect_np(0);
    g_tramp_a = Install(g_jit, tramp_a_start, tramp_a_slot, tramp_a_end);
    g_tramp_b = Install(g_jit + 0x2000, tramp_b_start, tramp_b_slot, tramp_b_end);
    pthread_jit_write_protect_np(1);
    sys_icache_invalidate(g_jit, 0x4000);

    static u8 alt_stack[1 << 16];
    stack_t ss{alt_stack, sizeof(alt_stack), 0};
    sigaltstack(&ss, nullptr);
    struct sigaction sa {};
    sa.sa_handler = OnFault;
    sa.sa_flags = SA_ONSTACK | SA_NODEFER;
    for (const int signal : {SIGILL, SIGSEGV, SIGBUS, SIGTRAP}) {
        sigaction(signal, &sa, nullptr);
    }

    // The State sits in the middle of its own buffer: under tramp_a it is the stack pointer.
    alignas(16) static u8 state_buffer[1 << 16];
    State& live = *reinterpret_cast<State*>(state_buffer + (1 << 15));

    u64 host_x18;
    asm volatile("mov %0, x18" : "=r"(host_x18));

    static u8 mem_before[MemSize], mem_interp[MemSize];
    const u64 mid = reinterpret_cast<u64>(g_mem) + MemSize / 2;

    struct Counts {
        u64 tried, handled, compared, mismatched, unpredictable, native_fault, asserted;
    };
    Counts counts[3]{};
    const char* const names[3] = {"general loads/stores", "ST1/LD1 single element", "DC ZVA"};
    u64 by_class[16]{};
    int printed = 0;

    for (u64 n = 0; n < iterations; ++n) {
        // Instruction.
        Kind kind;
        u32 instruction = static_cast<u32>(rng());
        const u32 pick = static_cast<u32>(rng() % 100);
        if (pick < 70) {
            kind = Kind::General;
            instruction = (instruction & ~(1U << 25)) | (1U << 27); // loads and stores
        } else if (pick < 95) {
            kind = Kind::St1Single;
            instruction = (instruction & ~0xBF000000U) | 0x0D000000U;
            if (rng() % 2) {
                instruction &= ~(0x1FU << 16); // Rm = 0: the form without post-index
            }
        } else {
            kind = Kind::DcZva;
            instruction = 0xD50B7420 | (instruction & 0x1F);
        }
        Counts& c = counts[static_cast<int>(kind)];
        ++c.tried;

        // State and memory.
        State before{};
        for (int i = 0; i < 31; ++i) {
            const u64 r = rng();
            switch (r % 10) {
            case 0:
                before.x[i] = (r >> 8) % 512; // a small index
                break;
            case 1:
                before.x[i] = static_cast<u64>(-static_cast<int64_t>((r >> 8) % 512));
                break;
            case 2:
                before.x[i] = (r >> 8) & 0xFFFFFFFF000001FFULL; // junk above a small low word
                break;
            default:
                before.x[i] = mid + static_cast<int64_t>((r >> 8) % 8192) - 4096;
                break;
            }
        }
        before.x[18] = host_x18;
        before.sp = (mid + static_cast<int64_t>(rng() % 4096) - 2048) & ~u64{15};
        for (auto& v : before.v) {
            v = {rng(), rng()};
        }
        for (size_t i = 0; i < MemSize; i += 8) {
            const u64 r = rng();
            std::memcpy(g_mem + i, &r, 8);
        }
        std::memcpy(mem_before, g_mem, MemSize);

        // Interpreter.
        State interp = before;
        g_out_of_bounds = false;
        g_assert_hit = false;
        bool special{};
        const bool handled = Interpret(interp, instruction, special);
        if (g_assert_hit) {
            ++c.asserted;
        }
        if (!handled || g_out_of_bounds || g_assert_hit) {
            std::memcpy(g_mem, mem_before, MemSize);
            continue;
        }
        ++c.handled;
        std::memcpy(mem_interp, g_mem, MemSize);
        std::memcpy(g_mem, mem_before, MemSize);

        // Native.
        const u32 rt = instruction & 31, rn = (instruction >> 5) & 31;
        const u32 rt2 = (instruction >> 10) & 31, rm = (instruction >> 16) & 31;
        const bool sp_base = kind != Kind::DcZva && rn == 31;
        if (sp_base && (rt == 28 || rt2 == 28 || rm == 28)) {
            continue; // x28 holds the state under tramp_b
        }
        if (rt == 18 || rt2 == 18) {
            continue; // x18 belongs to the platform
        }
        live = before;
        const int signal = RunNative(sp_base ? g_tramp_b : g_tramp_a, live, instruction);
        State native = live;
        if (!sp_base) {
            native.sp = interp.sp;
        }
        native.host_sp = interp.host_sp = 0;
        // Writeback into a register the instruction also transfers is unpredictable; the CPU's
        // choice there is not a reference.
        const bool pair = kind == Kind::General && ((instruction >> 27) & 7) == 5;
        const bool wback =
            kind == Kind::General &&
            (pair ? ((instruction >> 23) & 1) != 0
                  : ((instruction >> 24) & 1) == 0 && ((instruction >> 21) & 1) == 0 &&
                        ((instruction >> 10) & 1) != 0);
        const bool simd = ((instruction >> 26) & 1) != 0;
        const bool unpredictable =
            (wback && !simd && rn != 31 && (rt == rn || (pair && rt2 == rn))) ||
            (kind == Kind::St1Single && ((instruction >> 23) & 1) != 0 && rm == rn && rn != 31);
        // An acquire/release access to a misaligned address faults on real hardware.
        const bool misaligned_ordered =
            signal == SIGBUS && kind == Kind::General && (instruction & 0x3F000000) == 0x08000000;
        if (signal != 0 && (unpredictable || misaligned_ordered)) {
            // Apple's CPUs treat the unpredictable forms as undefined instructions.
            ++c.unpredictable;
            std::memcpy(g_mem, mem_before, MemSize);
            continue;
        }
        if (signal != 0) {
            ++c.native_fault;
            if (printed < 40) {
                ++printed;
                std::printf("NATIVE FAULT (signal %d) on an instruction the interpreter ran: "
                            "%08X (%s)\n",
                            signal, instruction, names[static_cast<int>(kind)]);
            }
            std::memcpy(g_mem, mem_before, MemSize);
            continue;
        }
        ++c.compared;
        if (kind == Kind::General) {
            // bits 29:28, 26 (SIMD), 24
            ++by_class[((instruction >> 28) & 3) << 2 | ((instruction >> 26) & 1) << 1 |
                       ((instruction >> 24) & 1)];
        }
        if (SameState(interp, native, sp_base) && std::memcmp(mem_interp, g_mem, MemSize) == 0) {
            continue;
        }
        if (unpredictable) {
            ++c.unpredictable;
            continue;
        }
        ++c.mismatched;
        if (printed < 40) {
            ++printed;
            Describe(names[static_cast<int>(kind)], instruction, before, interp, native,
                     mem_interp, g_mem, sp_base);
        }
    }

    std::printf("\nseed %llu, %llu iterations\n", seed, iterations);
    u64 mismatches = 0;
    for (int i = 0; i < 3; ++i) {
        const Counts& c = counts[i];
        std::printf("%-24s tried %llu, interpreted in bounds %llu, compared %llu, MISMATCHED "
                    "%llu, unpredictable (ignored) %llu, native fault %llu, assert %llu\n",
                    names[i], c.tried, c.handled, c.compared, c.mismatched, c.unpredictable,
                    c.native_fault, c.asserted);
        mismatches += c.mismatched + c.native_fault;
    }
    std::printf("general compared by encoding class (bits 29:28, SIMD, bit 24):");
    for (int i = 0; i < 16; ++i) {
        std::printf(" %d%d/%d/%d=%llu", (i >> 3) & 1, (i >> 2) & 1, (i >> 1) & 1, i & 1,
                    by_class[i]);
    }
    std::printf("\n");
    return mismatches == 0 ? 0 : 1;
}
