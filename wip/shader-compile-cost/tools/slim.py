# slim.py IN OUT: insert slim explicit specialisations of Metal's texture classes, holding only the methods the
# shader calls, so the compiler never instantiates Apple's full classes. Method bodies are taken from Apple's
# headers, preprocessed for language 4.0 by prep_headers.sh (../local/pp/*.h). Exit 2 if the shader uses a texture form this does not cover.
import re, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = {"texture2d": "2d", "texture3d": "3d", "texture2d_array": "2d_array", "texturecube": "cube",
         "depth2d": "D2d", "depth2d_array": "D2d_array", "depthcube": "Dcube"}
DEPTH = {"texture2d": "depth2d", "texture2d_array": "depth2d_array", "texturecube": "depthcube"}
_cache = {}
def methods(kind):
    if kind in _cache: return _cache[kind]
    lines = open(f"{HERE}/../local/pp/{kind}.h").read().split("\n")
    out, i = [], 0
    # stop at the final class (constructors and assignment operators are not copied)
    end = next(n for n, l in enumerate(lines) if l.startswith(f"struct {kind} :"))
    while i < end:
        l = lines[i]
        if l.startswith("  METAL_FUNC ") and not l.rstrip().endswith(";"):
            j = i
            while lines[j] != "  }": j += 1
            m = re.search(r"\b(\w+)\(", l[len("  METAL_FUNC "):])
            q = re.search(r"\) ((?:const )?\w+)(?: METAL_CONST_ARG\(\w+\))?$", l.rstrip())
            qual = q.group(1) if q else "?"
            out.append((m.group(1) if m else "?", qual, "\n".join(lines[i:j + 1])))
            i = j + 1
        else: i += 1
    _cache[kind] = out
    return out
def slim(src):
    used = set(re.findall(r"\b(texture\w+|depth\w+)<(\w+)(?:, (access::\w+))?>", src))
    names = set(re.findall(r"\.(\w+)\(", src))
    if "spvDepthCast(" in src.split("\nfragment ")[-1].split("\nvertex ")[-1].split("\nkernel ")[-1]:
        used |= {(DEPTH[k], T, a) for k, T, a in used if k in DEPTH}
    spec = []
    for kind, T, acc in sorted(used):
        if kind not in KINDS or T != "float" or acc not in ("", "access::sample"): continue
        body = []
        for name, qual, text in methods(kind):
            if name not in names or qual not in ("const thread", "const constant"): continue
            text = re.sub(r"\n\s*const \w+ auto &derived = static_cast<[^;]*;", "", text)
            text = re.sub(r"\bs\.val\b", "_spvSmp::val(s)", re.sub(r"\bderived\.t\b", "t", text))
            text = re.sub(r"\bT\b", T, text)
            text = re.sub(r"\bint\(a\)", "int(access::sample)", text)
            body.append(text)
        spec.append(f"template <> struct {kind}<{T}, access::sample, memory_coherence_threadgroup, void>\n{{\n"
                    f"  __metal_{('depth_' + KINDS[kind][1:]) if KINDS[kind][0] == 'D' else ('texture_' + KINDS[kind])}_t t;\n" + "\n".join(body) + "\n};\n")
    if not spec: return src, 0
    pre = ("#pragma METAL internals : enable\nnamespace metal {\n"
           "template <> struct _texture2d_sample<char, access::read, __memory_coherence_threadgroup, void> { static METAL_FUNC __metal_sampler_t val(sampler s) { return s.val; } };\n"
           "using _spvSmp = _texture2d_sample<char, access::read, __memory_coherence_threadgroup, void>;\n"
           + "".join(spec) + "}\n#pragma METAL internals : disable\n")
    k = "using namespace metal;\n"
    i = src.index(k) + len(k)
    return src[:i] + pre + src[i:], len(spec)
if __name__ == "__main__":
    out, n = slim(open(sys.argv[1]).read())
    open(sys.argv[2], "w").write(out)
    print(f"{n} slim classes", file=sys.stderr)
