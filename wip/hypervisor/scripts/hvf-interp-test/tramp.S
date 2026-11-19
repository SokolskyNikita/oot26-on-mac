// Position-independent trampolines, copied into a MAP_JIT page with one instruction patched in.
// State layout (harness.cpp): x[31] at 0, sp at 248, v[32] at 256, host_sp at 768.
//
// tramp_a: the tested instruction does not use SP as its base. SP holds the State pointer, so all
//          31 general registers carry test values.
// tramp_b: the tested instruction uses SP as its base. x28 holds the State pointer; the harness
//          skips instructions whose other register fields name x28.

.text
.p2align 4

.macro SAVE_HOST
    sub sp, sp, #176
    stp x19, x20, [sp, #0]
    stp x21, x22, [sp, #16]
    stp x23, x24, [sp, #32]
    stp x25, x26, [sp, #48]
    stp x27, x28, [sp, #64]
    stp x29, x30, [sp, #80]
    stp d8, d9, [sp, #96]
    stp d10, d11, [sp, #112]
    stp d12, d13, [sp, #128]
    stp d14, d15, [sp, #144]
    str x18, [sp, #160]
    mov x9, sp
    str x9, [x0, #768]
.endm

.macro RESTORE_HOST
    ldr x18, [sp, #160]
    ldp x19, x20, [sp, #0]
    ldp x21, x22, [sp, #16]
    ldp x23, x24, [sp, #32]
    ldp x25, x26, [sp, #48]
    ldp x27, x28, [sp, #64]
    ldp x29, x30, [sp, #80]
    ldp d8, d9, [sp, #96]
    ldp d10, d11, [sp, #112]
    ldp d12, d13, [sp, #128]
    ldp d14, d15, [sp, #144]
    add sp, sp, #176
    ret
.endm

.macro VECS op, base
    \op q0, q1, [\base, #256]
    \op q2, q3, [\base, #288]
    \op q4, q5, [\base, #320]
    \op q6, q7, [\base, #352]
    \op q8, q9, [\base, #384]
    \op q10, q11, [\base, #416]
    \op q12, q13, [\base, #448]
    \op q14, q15, [\base, #480]
    \op q16, q17, [\base, #512]
    \op q18, q19, [\base, #544]
    \op q20, q21, [\base, #576]
    \op q22, q23, [\base, #608]
    \op q24, q25, [\base, #640]
    \op q26, q27, [\base, #672]
    \op q28, q29, [\base, #704]
    \op q30, q31, [\base, #736]
.endm

.macro GPRS_LOW op, base
    \op x0, x1, [\base, #0]
    \op x2, x3, [\base, #16]
    \op x4, x5, [\base, #32]
    \op x6, x7, [\base, #48]
    \op x8, x9, [\base, #64]
    \op x10, x11, [\base, #80]
    \op x12, x13, [\base, #96]
    \op x14, x15, [\base, #112]
    \op x16, x17, [\base, #128]
    \op x18, x19, [\base, #144]
    \op x20, x21, [\base, #160]
    \op x22, x23, [\base, #176]
    \op x24, x25, [\base, #192]
    \op x26, x27, [\base, #208]
.endm

.globl _tramp_a_start, _tramp_a_slot, _tramp_a_end
_tramp_a_start:
    SAVE_HOST
    mov sp, x0
    VECS ldp, sp
    GPRS_LOW ldp, sp
    ldp x28, x29, [sp, #224]
    ldr x30, [sp, #240]
_tramp_a_slot:
    nop
    GPRS_LOW stp, sp
    stp x28, x29, [sp, #224]
    str x30, [sp, #240]
    VECS stp, sp
    ldr x9, [sp, #768]
    mov sp, x9
    RESTORE_HOST
_tramp_a_end:

.globl _tramp_b_start, _tramp_b_slot, _tramp_b_end
_tramp_b_start:
    SAVE_HOST
    mov x28, x0
    ldr x9, [x28, #248]
    mov sp, x9
    VECS ldp, x28
    GPRS_LOW ldp, x28
    ldr x29, [x28, #232]
    ldr x30, [x28, #240]
_tramp_b_slot:
    nop
    GPRS_LOW stp, x28
    str x29, [x28, #232]
    str x30, [x28, #240]
    VECS stp, x28
    mov x9, sp
    str x9, [x28, #248]
    ldr x9, [x28, #768]
    mov sp, x9
    RESTORE_HOST
_tramp_b_end:
