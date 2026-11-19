import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let src = """
#include <metal_stdlib>
using namespace metal;
struct Set { const device uint* p [[id(0)]]; };
kernel void viaArg(const device Set& s [[buffer(0)]], device const uint* idx [[buffer(1)]], device uint* o [[buffer(2)]], uint id [[thread_position_in_grid]]) { o[id] = s.p[idx[id]]; }
kernel void direct(device const uint* p [[buffer(0)]], device const uint* idx [[buffer(1)]], device uint* o [[buffer(2)]], uint id [[thread_position_in_grid]]) { o[id] = p[idx[id]]; }
"""
let lib = try! dev.makeLibrary(source: src, options: nil)
let words = 16384, bindOff = 4096, rangeWords = 256   // 64 KiB buffer; "Vulkan" binding = bytes 4096..5120
let data = dev.makeBuffer(length: words * 4, options: .storageModeShared)!
let dp = data.contents().bindMemory(to: UInt32.self, capacity: words); for i in 0..<words { dp[i] = 0xA0000000 | UInt32(i) }
let endIdx = UInt32(words - bindOff / 4)   // first index past the end of the MTLBuffer
let cases: [(String, UInt32)] = [("inside binding", 10), ("last word of binding", UInt32(rangeWords - 1)), ("1 word past binding, inside MTLBuffer", UInt32(rangeWords)),
    ("far past binding, inside MTLBuffer", 8000), ("last word of MTLBuffer", endIdx - 1), ("1 word past MTLBuffer", endIdx), ("64 KiB past MTLBuffer", endIdx + 16384),
    ("16 MiB past MTLBuffer", endIdx + (4 << 20)), ("1 GiB past", 1 << 28), ("index 0xFFFFFFFF", 0xFFFFFFFF)]
print("device \(dev.name); data buffer allocatedSize \(data.allocatedSize) bytes for length \(data.length)")
for mode in ["viaArg", "direct"] {
    let p = try! dev.makeComputePipelineState(function: lib.makeFunction(name: mode)!)
    for (name, ix) in cases {   // one case per command buffer so a fault is attributed
        var i = ix; let ib = dev.makeBuffer(bytes: &i, length: 4)!, ob = dev.makeBuffer(length: 4)!
        ob.contents().storeBytes(of: 0xDEADBEEF, as: UInt32.self)
        let cb = q.makeCommandBuffer()!, e = cb.makeComputeCommandEncoder()!; e.setComputePipelineState(p)
        if mode == "viaArg" { let ab = dev.makeBuffer(length: 8)!; ab.contents().storeBytes(of: data.gpuAddress + UInt64(bindOff), as: UInt64.self)
            e.setBuffer(ab, offset: 0, index: 0); e.useResource(data, usage: .read) } else { e.setBuffer(data, offset: bindOff, index: 0) }
        e.setBuffer(ib, offset: 0, index: 1); e.setBuffer(ob, offset: 0, index: 2)
        e.dispatchThreads(MTLSize(width: 1, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: 1, height: 1, depth: 1)); e.endEncoding(); cb.commit(); cb.waitUntilCompleted()
        let v = ob.contents().load(as: UInt32.self); let expect = 0xA0000000 | (UInt32(bindOff / 4) &+ ix)
        let verdict = v == 0xDEADBEEF ? "NOT WRITTEN" : v == 0 ? "zero" : (ix < endIdx && v == expect) ? "real buffer contents" : "other data"
        print(String(format: "%-7@ %-38@ -> 0x%08X  %@  status %d %@", mode as NSString, name as NSString, v, verdict as NSString, cb.status.rawValue, (cb.error?.localizedDescription ?? "") as NSString))
    }
}
