// mtltime: time the Metal half of a shader compile, the way MoltenVK drives it.
// Usage: mtltime VS.metal FS.metal [safe|relaxed|fast]
// Steps timed: MTLDevice.makeLibrary(source:) per stage (MSL -> AIR), makeFunction, and
// makeRenderPipelineState (AIR -> GPU machine code). The vertex descriptor is built from the vertex
// function's reflected attributes and the colour attachments from the fragment source's [[color(n)]] outputs.
import Metal
import Foundation

func ms(_ t0: UInt64, _ t1: UInt64) -> String { String(format: "%.2f", Double(t1 - t0) / 1e6) }
func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }

let args = CommandLine.arguments
let dev = MTLCreateSystemDefaultDevice()!
let mode = args.count > 3 ? args[3] : "safe"
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = .version4_0
    o.mathMode = mode == "fast" ? .fast : mode == "relaxed" ? .relaxed : .safe
    o.mathFloatingPointFunctions = mode == "fast" ? .fast : .precise
    return o
}
func load(_ path: String, _ label: String) -> (MTLLibrary, String) {
    let src = try! String(contentsOfFile: path, encoding: .utf8)
    let t0 = now()
    let lib = try! dev.makeLibrary(source: src, options: options())
    print("\(label) makeLibrary(source) ms: \(ms(t0, now()))   (\(src.utf8.count) bytes of MSL)")
    return (lib, src)
}
let (vlib, _) = load(args[1], "vertex  ")
let (flib, fsrc) = load(args[2], "fragment")
let t0 = now()
let vfn = vlib.functionNames.compactMap { vlib.makeFunction(name: $0) }.first { $0.functionType == .vertex }!
let ffn = flib.functionNames.compactMap { flib.makeFunction(name: $0) }.first { $0.functionType == .fragment }!
print("makeFunction x2 ms: \(ms(t0, now()))")

let d = MTLRenderPipelineDescriptor()
d.vertexFunction = vfn
d.fragmentFunction = ffn
let vd = MTLVertexDescriptor()
var offset = 0
for a in vfn.vertexAttributes ?? [] where a.isActive {
    let f: MTLVertexFormat
    switch a.attributeType {
    case .float: f = .float
    case .float2: f = .float2
    case .float3: f = .float3
    case .float4: f = .float4
    case .int, .uint: f = a.attributeType == .int ? .int : .uint
    case .int2: f = .int2
    case .int3: f = .int3
    case .int4: f = .int4
    case .uint2: f = .uint2
    case .uint3: f = .uint3
    case .uint4: f = .uint4
    default: f = .float4
    }
    vd.attributes[a.attributeIndex].format = f
    vd.attributes[a.attributeIndex].offset = offset
    vd.attributes[a.attributeIndex].bufferIndex = 30
    offset += 16
}
if offset > 0 {
    vd.layouts[30].stride = offset
    d.vertexDescriptor = vd
}
// Colour outputs: "float4 name [[color(n)]]" / "uint4 ..." / "int4 ..."
let re = try! NSRegularExpression(pattern: #"(\w+)\s+\w+\s*\[\[color\((\d+)\)"#)
var outs: [(Int, String)] = []
for m in re.matches(in: fsrc, range: NSRange(fsrc.startIndex..., in: fsrc)) {
    let ty = String(fsrc[Range(m.range(at: 1), in: fsrc)!])
    let idx = Int(fsrc[Range(m.range(at: 2), in: fsrc)!])!
    outs.append((idx, ty))
    d.colorAttachments[idx].pixelFormat = ty.hasPrefix("uint") ? .rgba32Uint : ty.hasPrefix("int") ? .rgba32Sint : .rgba16Float
}
d.depthAttachmentPixelFormat = .depth32Float
print("vertex attributes: \(vfn.vertexAttributes?.filter { $0.isActive }.count ?? 0), colour outputs: \(outs.sorted { $0.0 < $1.0 })")
let t1 = now()
do {
    _ = try dev.makeRenderPipelineState(descriptor: d, options: [], reflection: nil)
    print("makeRenderPipelineState ms: \(ms(t1, now()))")
} catch {
    print("PIPELINE ERROR after \(ms(t1, now())) ms: \(error.localizedDescription.prefix(600))")
}
