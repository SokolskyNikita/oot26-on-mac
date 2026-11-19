// mtlconc: does Metal compile several shaders at once? Usage: mtlconc K [max] VS.metal FS.metal
// Compiles K freshly renamed copies of the pair concurrently, then builds the K pipelines concurrently, and
// prints the wall time of each phase. "max" sets MTLDevice.shouldMaximizeConcurrentCompilation first.
import Metal
import Foundation
func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
var a = Array(CommandLine.arguments.dropFirst())
let k = Int(a.removeFirst())!
let dev = MTLCreateSystemDefaultDevice()!
if a[0] == "max" { a.removeFirst(); dev.shouldMaximizeConcurrentCompilation = true }
print("K=\(k) shouldMaximizeConcurrentCompilation=\(dev.shouldMaximizeConcurrentCompilation) maximumConcurrentCompilationTaskCount=\(dev.maximumConcurrentCompilationTaskCount)")
let vs0 = try! String(contentsOfFile: a[0], encoding: .utf8), fs0 = try! String(contentsOfFile: a[1], encoding: .utf8)
// warm the compiler service so its start-up is not counted
_ = try! dev.makeLibrary(source: "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }", options: nil)
var descs = [MTLRenderPipelineDescriptor?](repeating: nil, count: k)
let lock = NSLock()
let o = MTLCompileOptions(); o.languageVersion = .version4_0; o.mathMode = .safe; o.mathFloatingPointFunctions = .precise
var t = now()
DispatchQueue.concurrentPerform(iterations: k) { i in
    let n = "m\(UInt32.random(in: 0..<UInt32.max))x"
    let vl = try! dev.makeLibrary(source: vs0.replacingOccurrences(of: "main0", with: n), options: o)
    let fl = try! dev.makeLibrary(source: fs0.replacingOccurrences(of: "main0", with: n), options: o)
    let d = MTLRenderPipelineDescriptor()
    d.vertexFunction = vl.makeFunction(name: n)!; d.fragmentFunction = fl.makeFunction(name: n)!
    let vd = MTLVertexDescriptor(); var off = 0
    for at in d.vertexFunction!.vertexAttributes ?? [] where at.isActive {
        vd.attributes[at.attributeIndex].format = .float4; vd.attributes[at.attributeIndex].offset = off
        vd.attributes[at.attributeIndex].bufferIndex = 30; off += 16
    }
    vd.layouts[30].stride = off; d.vertexDescriptor = vd
    d.colorAttachments[0].pixelFormat = .rgba16Float; d.depthAttachmentPixelFormat = .depth32Float
    lock.lock(); descs[i] = d; lock.unlock()
}
print(String(format: "libraries: %.0f ms wall for %d pairs", Double(now() - t) / 1e6, k))
t = now()
DispatchQueue.concurrentPerform(iterations: k) { i in
    _ = try! dev.makeRenderPipelineState(descriptor: descs[i]!, options: [], reflection: nil)
}
print(String(format: "pipelines: %.0f ms wall for %d pipelines", Double(now() - t) / 1e6, k))
