# profsum.py PROFILE: attribute every sample under the compile request to the deepest "pass-like" frame on its stack.
import re, sys, collections
L = open(sys.argv[1]).read().split("\n")
start = max((i for i, l in enumerate(L) if "split_stack_call" in l), key=lambda i: int(re.search(r"(\d+) split_stack_call", L[i]).group(1)))
rx = re.compile(r"^(\s+[+!:| ]*)(\d+) (.+?)  \(in ([^)]+)\)")
nodes = []; base = None
for l in L[start:]:
    m = rx.match(l)
    if not m: break
    d = len(m.group(1))
    if base is None: base = d
    elif d <= base: break
    nodes.append((d, int(m.group(2)), m.group(3), m.group(4)))
total = nodes[0][1]
SKIP = ("PassManager", "PassAdaptor", "FPPassManager", "MPPassManager", "CGSCC", "RepeatedPass", "DevirtSCC", "PassModel", "ModuleInlinerWrapper")
def label(name, lib):
    m = re.match(r"(?:\(anonymous namespace\)::|llvm::(?:\w+::)*)?([\w<>:, ]+?)::(run|runOnFunction|runOnMachineFunction|runOnModule|runImpl|runOnSCC)\(", name)
    if m and not any(s in name for s in SKIP): return m.group(1).split("::")[-1]
    return None
phase_keys = [("__clang_metalfe_GPUCompiler_compileFromSourceWrapper", "FE"), ("linkToBufferWrapper", "FE link"), ("AIRNTEmitPipelineImage", "BE"), ("runFrameworkPasses", "BE framework lowering"), ("readModuleFromBinaryRequest", "BE read bitcode")]
agg = collections.Counter(); stack = []
for i, (d, n, name, lib) in enumerate(nodes):
    while stack and stack[-1][0] >= d: stack.pop()
    stack.append((d, name, lib))
    child = sum(nodes[j][1] for j in range(i + 1, len(nodes)) if nodes[j][0] == d + 2 and all(nodes[k][0] > d for k in range(i + 1, j + 1))) if i + 1 < len(nodes) and nodes[i + 1][0] > d else 0
    # children: contiguous deeper block; sum only direct children
    self_n = n - child
    if self_n <= 0: continue
    phase = "other"; lab = None
    for dd, nm, lb in stack:
        for k, p in phase_keys:
            if k in nm: phase = p
        x = label(nm, lb)
        if x: lab = x
    if lab is None:
        libs = [lb for _, _, lb in stack]
        lab = "(clang parse/sema/codegen, unsymbolised)" if phase == "FE" else "(driver glue: " + stack[-1][2] + ")"
    agg[(phase, lab)] += self_n
print("total samples", total)
byphase = collections.Counter()
for (p, l), n in agg.items(): byphase[p] += n
for p, n in byphase.most_common():
    print(f"\n{p}: {100*n/total:.1f}%")
    rest = 0
    for (pp, l), m in sorted(agg.items(), key=lambda x: -x[1]):
        if pp != p: continue
        if 100 * m / total >= 0.7: print(f"   {100*m/total:5.1f}%  {l}")
        else: rest += m
    if rest: print(f"   {100*rest/total:5.1f}%  (smaller items)")
