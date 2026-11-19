// mathprobe: what Apple's GPU returns for the operations the translated shader relies on, in safe/precise and fast modes.
import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let src = """
#include <metal_stdlib>
using namespace metal;
template<typename T> T spvFMul(T l, T r) {
    #pragma metal fp math_mode(safe)
    #pragma metal fp contract(off)
    return fma(l, r, T(-0.0)); }
template<typename T> T spvFAdd(T l, T r) {
    #pragma metal fp math_mode(safe)
    #pragma metal fp contract(off)
    return fma(T(1), l, r); }
kernel void k(device const float* a, device const float* b, device float* o, uint id [[thread_position_in_grid]]) {
    float x = a[id], y = b[id]; uint p = id * 16u;
    o[p+0] = PRE exp2(x); o[p+1] = PRE log2(x); o[p+2] = PRE rsqrt(x); o[p+3] = PRE sqrt(x); o[p+4] = 1.0 / x;
    o[p+5] = spvFMul(x, y); o[p+6] = x * y; o[p+7] = spvFAdd(x, y); o[p+8] = x + y;
    o[p+9] = PRE min(x, y); o[p+10] = PRE max(x, y); o[p+11] = PRE min(PRE max(x, 0.0), 1.0);
    o[p+12] = x * y + a[(id + 1u) % N]; o[p+13] = fma(x, y, a[(id + 1u) % N]); o[p+14] = float(uint(rint(x))); o[p+15] = float(int(trunc(x)));
}
"""
let N = 1 << 20
var rng: UInt64 = 12345
func r() -> UInt32 { rng = rng &* 6364136223846793005 &+ 1442695040888963407; return UInt32(truncatingIfNeeded: rng >> 33) }
var A = [Float](repeating: 0, count: N), B = [Float](repeating: 0, count: N)
for i in 0..<N { // mostly ordinary magnitudes, some full-range bit patterns
    if i % 8 == 7 { A[i] = Float(bitPattern: r() << 1 | (r() & 1)); B[i] = Float(bitPattern: r() << 1 | (r() & 1)) }
    else { A[i] = Float(r() & 0xFFFFFF) / Float(1 << 24) * 64 - (i % 2 == 0 ? 0 : 32); B[i] = Float(r() & 0xFFFFFF) / Float(1 << 24) * 8 - 4 } }
let special: [Float] = [.nan, 0, -0.0, .infinity, -.infinity, 1e-39, -1e-39, 1, -1, 0.5, 1.5, 2.5, 3.4e38, Float.leastNormalMagnitude]
for (i, s) in special.enumerated() { for (j, t) in special.enumerated() { A[i * 16 + j] = s; B[i * 16 + j] = t } }
func ulps(_ g: Float, _ e: Float) -> Double { if g == e || (g.isNaN && e.isNaN) { return 0 }; if !g.isFinite || !e.isFinite { return .infinity }; return abs(Double(g) - Double(e)) / Double(e.ulp) }
for fast in [false, true] {
    let o = MTLCompileOptions(); o.languageVersion = .version3_2; o.mathMode = fast ? .fast : .safe; o.mathFloatingPointFunctions = fast ? .fast : .precise
    let s = src.replacingOccurrences(of: "PRE ", with: fast ? "" : "precise::").replacingOccurrences(of: "% N", with: "% \(N)u")
    let f = try! dev.makeLibrary(source: s, options: o).makeFunction(name: "k")!; let p = try! dev.makeComputePipelineState(function: f)
    let ba = dev.makeBuffer(bytes: A, length: N * 4)!, bb = dev.makeBuffer(bytes: B, length: N * 4)!, bo = dev.makeBuffer(length: N * 64)!
    let cb = q.makeCommandBuffer()!, e = cb.makeComputeCommandEncoder()!; e.setComputePipelineState(p); e.setBuffer(ba, offset: 0, index: 0); e.setBuffer(bb, offset: 0, index: 1); e.setBuffer(bo, offset: 0, index: 2)
    e.dispatchThreads(MTLSize(width: N, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: 64, height: 1, depth: 1)); e.endEncoding(); cb.commit(); cb.waitUntilCompleted()
    let O = bo.contents().bindMemory(to: Float.self, capacity: N * 16)
    print("=== \(fast ? "fast math" : "safe math, precise functions (what the emulator uses)")")
    let names = ["exp2", "log2", "rsqrt", "sqrt", "1/x"]
    for (c, nm) in names.enumerated() {
        var exact = 0, n = 0; var worst = 0.0
        for i in 256..<N { let x = A[i]; if !(x.isFinite) || (c >= 1 && c <= 3 && x <= 0) || x == 0 || abs(x) < 1e-30 || abs(x) > 1e30 { continue }
            let d = Double(x); let ref = Float([Foundation.exp2(d), Foundation.log2(d), 1 / d.squareRoot(), d.squareRoot(), 1 / d][c]); if !ref.isFinite || ref.isSubnormal { continue }
            let u = ulps(O[i * 16 + c], ref); n += 1; if u == 0 { exact += 1 }; worst = max(worst, u) }
        print(String(format: "%-6@ correctly rounded %6.2f%%  worst error %.2f ulp  (%d inputs)", nm as NSString, 100 * Double(exact) / Double(n), worst, n))
    }
    var mulDiff = 0, addDiff = 0, fmaContract = 0, fmaWrong = 0, cnt = 0
    for i in 0..<N { let x = A[i], y = B[i]; cnt += 1
        func same(_ a: Float, _ b: Float) -> Bool { a.bitPattern == b.bitPattern || (a.isNaN && b.isNaN) }
        if !same(O[i*16+5], x * y) && !(x * y).isSubnormal { mulDiff += 1 }; if !same(O[i*16+7], x + y) && !(x + y).isSubnormal { addDiff += 1 }
        let z = A[(i + 1) % N]; let sep = x * y + z, fused = (x * y).addingProduct(0, 0) == 0 ? x.addingProduct(0,0) : 0; _ = fused
        let fu = z.addingProduct(x, y)
        if !same(O[i*16+12], sep) && same(O[i*16+12], fu) && !sep.isSubnormal { fmaContract += 1 }
        if !same(O[i*16+13], fu) && !fu.isSubnormal { fmaWrong += 1 } }
    print("fma(x,y,-0) != CPU x*y: \(mulDiff) of \(cnt);  fma(1,x,y) != CPU x+y: \(addDiff);  explicit fma != CPU fused: \(fmaWrong);  plain x*y+z silently fused: \(fmaContract)")
    func at(_ s: Float, _ t: Float, _ c: Int) -> Float { O[(special.firstIndex(where: { $0.bitPattern == s.bitPattern })! * 16 + special.firstIndex(where: { $0.bitPattern == t.bitPattern })!) * 16 + c] }
    print("min(NaN,1)=\(at(.nan, 1, 9)) min(1,NaN)=\(at(1, .nan, 9)) max(NaN,1)=\(at(.nan, 1, 10)) max(1,NaN)=\(at(1, .nan, 10)) saturate-pattern(NaN)=\(at(.nan, 1, 11)) min(0,-0)=\(at(0, -0.0, 9)) min(-0,0)=\(at(-0.0, 0, 9))")
    print("denormal: 1e-39*1=\(at(1e-39, 1, 6)) (bits \(String(at(1e-39, 1, 6).bitPattern, radix: 16)))  leastNormal*0.5=\(at(Float.leastNormalMagnitude, 0.5, 6))  1e-39+0=\(at(1e-39, 0, 8))")
    print("uint(rint(x)): 0.5->\(at(0.5, 1, 14)) 1.5->\(at(1.5, 1, 14)) 2.5->\(at(2.5, 1, 14)) -1->\(at(-1, 1, 14)) NaN->\(at(.nan, 1, 14)) inf->\(at(.infinity, 1, 14));  int(trunc(x)): NaN->\(at(.nan, 1, 15)) inf->\(at(.infinity, 1, 15)) -inf->\(at(-.infinity, 1, 15))")
}
