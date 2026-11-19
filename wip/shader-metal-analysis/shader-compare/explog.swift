import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let src = """
#include <metal_stdlib>
using namespace metal;
kernel void k(device const float* a, device float* o, uint id [[thread_position_in_grid]]) {
    float x = a[id]; uint p = id * 8u;
    o[p+0] = precise::exp2(x); o[p+1] = exp2(x); o[p+2] = fast::exp2(x); o[p+3] = precise::pow(2.0f, x);
    o[p+4] = precise::log2(x); o[p+5] = log2(x); o[p+6] = fast::log2(x); o[p+7] = precise::log(x) * 1.44269504088896340736f;
}
"""
let N = 1 << 21
var rng: UInt64 = 777
func r() -> UInt32 { rng = rng &* 6364136223846793005 &+ 1442695040888963407; return UInt32(truncatingIfNeeded: rng >> 33) }
var A = [Float](repeating: 0, count: N)
for i in 0..<N {
    switch i % 4 {
    case 0: A[i] = Float(r() & 0xFFFFFF) / Float(1 << 24) * 200 - 100      // exp2 range
    case 1: A[i] = Float(bitPattern: (r() % 0x7f000000) + 0x00800000)       // any positive normal (log2)
    case 2: A[i] = Float(r() & 0xFFFFFF) / Float(1 << 24) * 16               // typical shader values
    default: A[i] = Float(Int(r() % 201) - 100) }                            // integers
}
for k in 0..<64 { A[k] = Float(sign: .plus, exponent: k - 32, significand: 1) } // powers of two
func ulps(_ g: Float, _ e: Float) -> Double { if g == e { return 0 }; if !g.isFinite || !e.isFinite { return 99 }; return abs(Double(g) - Double(e)) / Double(e.ulp) }
let o = MTLCompileOptions(); o.languageVersion = .version3_2; o.mathMode = .safe; o.mathFloatingPointFunctions = .precise
let f = try! dev.makeLibrary(source: src, options: o).makeFunction(name: "k")!; let p = try! dev.makeComputePipelineState(function: f)
let ba = dev.makeBuffer(bytes: A, length: N * 4)!, bo = dev.makeBuffer(length: N * 32)!
let cb = q.makeCommandBuffer()!, e = cb.makeComputeCommandEncoder()!; e.setComputePipelineState(p); e.setBuffer(ba, offset: 0, index: 0); e.setBuffer(bo, offset: 0, index: 1)
e.dispatchThreads(MTLSize(width: N, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: 64, height: 1, depth: 1)); e.endEncoding(); cb.commit(); cb.waitUntilCompleted()
let O = bo.contents().bindMemory(to: Float.self, capacity: N * 8)
print("device: \(dev.name)")
let names = ["precise::exp2", "exp2 (default)", "fast::exp2", "precise::pow(2,x)", "precise::log2", "log2 (default)", "fast::log2", "precise::log*const"]
for c in 0..<8 {
    var h = [Int](repeating: 0, count: 6), n = 0; var worst = 0.0, wx: Float = 0, same = 0
    var cpuExact = 0
    for i in 0..<N { let x = A[i]; let isExp = c < 4
        if isExp { if abs(x) > 100 { continue } } else { if !(x > 0) || !x.isNormal { continue } }
        let d = Double(x); let ref = Float(isExp ? Foundation.exp2(d) : Foundation.log2(d)); if !ref.isNormal && ref != 0 { continue }
        let g = O[i * 8 + c]; let u = ulps(g, ref); n += 1; h[min(5, Int(u.rounded(.up)))] += 1; if u > worst { worst = u; wx = x }
        if g.bitPattern == O[i * 8 + (isExp ? 0 : 4)].bitPattern { same += 1 }
        let cpu = isExp ? Foundation.exp2(x) : Foundation.log2(x); if cpu == ref { cpuExact += 1 } }
    print(String(format: "%-20@ n=%d exact %.2f%%  <=1ulp %.2f%%  <=2 %.2f%%  <=3 %.2f%%  worse %d  worst %.2f ulp at x=%g  | bit-same as precise:: %.2f%%  | CPU libm float exact %.2f%%",
        names[c] as NSString, n, 100*Double(h[0])/Double(n), 100*Double(h[0]+h[1])/Double(n), 100*Double(h[0]+h[1]+h[2])/Double(n), 100*Double(h[0]+h[1]+h[2]+h[3])/Double(n), h[4]+h[5], worst, wx, 100*Double(same)/Double(n), 100*Double(cpuExact)/Double(n)))
}
var pe = 0, pl = 0, ie = 0, ic = 0
for k in 0..<64 { if O[k*8+4] == Float(k - 32) { pl += 1 } }
for i in 0..<N where i % 4 == 3 && i >= 64 { ic += 1; if O[i*8+0] == Float(Foundation.exp2(Double(A[i]))) { ie += 1 } }
print("precise::log2(2^k) exact: \(pl)/64   precise::exp2(integer) exact: \(ie)/\(ic)"); _ = pe
