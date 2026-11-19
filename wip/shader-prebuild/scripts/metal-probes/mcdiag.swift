// mcdiag: compile a fixed vertex + fragment MSL pair and build one render pipeline, timing each call.
// Usage: mcdiag [--seed N] [--reps N] [--sleep SEC] [--archive]   (--archive also adds the pipeline to an in-memory MTLBinaryArchive)
// The source is fixed for a given seed, so a second run of the same seed should be answered from
// Metal's on-disk shader cache. Bundle id local.metal-cache-diag comes from the embedded Info.plist.
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ t: UInt64) -> String { String(format: "%.2f ms", Double(now() - t) / 1e6) }
var seed = 1, reps = 1, sleepSec = 0.0, useArchive = false
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    switch a { case "--seed": seed = Int(it.next()!)!; case "--reps": reps = Int(it.next()!)!; case "--sleep": sleepSec = Double(it.next()!)!; case "--archive": useArchive = true; default: break }
}
let vsrc = """
#include <metal_stdlib>
using namespace metal;
struct VIn { float4 pos [[attribute(0)]]; float4 col [[attribute(1)]]; };
struct VOut { float4 pos [[position]]; float4 col; };
vertex VOut vmain(VIn in [[stage_in]]) { VOut o; o.pos = in.pos; o.col = in.col * \(seed).0; return o; }
"""
var fsrc = """
#include <metal_stdlib>
using namespace metal;
struct VOut { float4 pos [[position]]; float4 col; };
fragment float4 fmain(VOut in [[stage_in]], texture2d<float> t [[texture(0)]], sampler sm [[sampler(0)]]) {
 float4 v = in.col;

"""
for i in 0..<300 {
    fsrc += " v = sin(v * float4(\(i % 7 + 1).\(seed % 10)) + t.sample(sm, v.xy + float2(\(i).0)).zwxy) * cos(v.yzwx + \(i).5);\n"
    if i % 50 == 0 { fsrc += " if (v.x > \(i).0) { v = sqrt(abs(v)) + v.wzyx; }\n" }
}
fsrc += " return v; }\n"

print("bundle id: \(Bundle.main.bundleIdentifier ?? "nil")  seed \(seed)")
let dev = MTLCreateSystemDefaultDevice()!
for r in 0..<reps {
    var t = now()
    let vlib = try! dev.makeLibrary(source: vsrc, options: MTLCompileOptions()); let tv = ms(t)
    t = now()
    let flib = try! dev.makeLibrary(source: fsrc, options: MTLCompileOptions()); let tf = ms(t)
    let d = MTLRenderPipelineDescriptor()
    d.vertexFunction = vlib.makeFunction(name: "vmain")
    d.fragmentFunction = flib.makeFunction(name: "fmain")
    d.colorAttachments[0].pixelFormat = .bgra8Unorm
    let vd = MTLVertexDescriptor()
    vd.attributes[0].format = .float4; vd.attributes[0].offset = 0; vd.attributes[0].bufferIndex = 0
    vd.attributes[1].format = .float4; vd.attributes[1].offset = 16; vd.attributes[1].bufferIndex = 0
    vd.layouts[0].stride = 32
    d.vertexDescriptor = vd
    t = now()
    _ = try! dev.makeRenderPipelineState(descriptor: d)
    print("rep \(r): vlib \(tv) | flib \(tf) | pipe \(ms(t))")
    if useArchive {
        let ad = MTLBinaryArchiveDescriptor()
        let arch = try! dev.makeBinaryArchive(descriptor: ad)
        t = now(); try! arch.addRenderPipelineFunctions(descriptor: d); print("archive add: \(ms(t))")
        d.binaryArchives = [arch]
        t = now()
        do { _ = try dev.makeRenderPipelineState(descriptor: d, options: MTLPipelineOption(rawValue: 1 << 2) /* failOnBinaryArchiveMiss */, reflection: nil); print("pipe from archive (failOnMiss): \(ms(t))") }
        catch { print("pipe from archive failed: \(error.localizedDescription)") }
    }
}
if sleepSec > 0 { Thread.sleep(forTimeInterval: sleepSec) }
