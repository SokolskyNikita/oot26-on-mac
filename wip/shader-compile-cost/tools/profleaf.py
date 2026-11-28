# profleaf.py PROFILE: for chosen stack selectors, list where the samples end up (self time) and the first named callee.
import re, sys, collections
L = open(sys.argv[1]).read().split("\n")
rx = re.compile(r"^(\s+[+!:| ]*)(\d+) (.+?)  \(in ([^)]+)\)(.*)")
start = max((i for i, l in enumerate(L) if "split_stack_call" in l), key=lambda i: int(re.search(r"(\d+) split_stack_call", L[i]).group(1)))
nodes = []; base = None
for l in L[start:]:
    m = rx.match(l)
    if not m: break
    d = len(m.group(1))
    if base is None: base = d
    elif d <= base: break
    a = re.search(r"\[(0x[0-9a-f]+)\]", m.group(5))
    nodes.append((d, int(m.group(2)), re.sub(r"\(.*", "", m.group(3))[:64], m.group(4), a.group(1) if a else ""))
total = nodes[0][1]
# self counts
selfs = []
for i, (d, n, *_r) in enumerate(nodes):
    c = 0; j = i + 1
    while j < len(nodes) and nodes[j][0] > d:
        if nodes[j][0] == d + 2: c += nodes[j][1]
        j += 1
    selfs.append(n - c)
SEL = [("FE InstCombine", lambda st: any("compileFromSource" in s[2] for s in st) and any(s[2].endswith("InstCombinePass::run") for s in st)),
       ("FE unsymbolised (no pass on stack)", lambda st: any("compileFromSource" in s[2] for s in st) and not any("Pass" in s[2] for s in st)),
       ("BE machine passes", lambda st: any("MachineFunctionPass::runOnFunction" in s[2] for s in st)),
       ("BE outside named passes", lambda st: any("AIRNTEmitPipelineImage" in s[2] for s in st) and not any("Pass" in s[2] for s in st)),
       ("FE LICM", lambda st: any("compileFromSource" in s[2] for s in st) and any("LICMPass::run" in s[2] for s in st))]
res = {k: [0, collections.Counter(), collections.Counter()] for k, _ in SEL}
stack = []
for i, nd in enumerate(nodes):
    while stack and stack[-1][0] >= nd[0]: stack.pop()
    stack.append(nd)
    if selfs[i] <= 0: continue
    for k, f in SEL:
        if f(stack):
            res[k][0] += selfs[i]
            res[k][1][f"{nd[2]} [{nd[3].split('.')[0]}]"] += selfs[i]
            named = [s[2] for s in stack if s[2] != "???" and ("llvm::" in s[2] or "clang" in s[2])]
            res[k][2][named[-1] if named else "?"] += selfs[i]
for k, (n, leaf, deep) in res.items():
    print(f"\n== {k}: {100*n/total:.1f}% of all samples")
    print("  self time by function:")
    for a, b in leaf.most_common(9): print(f"    {100*b/total:4.1f}%  {a}")
    print("  by deepest named LLVM frame:")
    for a, b in deep.most_common(9): print(f"    {100*b/total:4.1f}%  {a}")
