// stages: build pipelines for vertex, compute, mesh and object MSL the way bench builds fragment pipelines, and write
// one binary archive per source file.
// Usage: MTL_SHADER_CACHE_SIZE=0 stages -stage vs|cs|ms|os [-archivedir DIR] [-j N] [-fs trivial|full]
//        [-obj none|syn] [-q] FILE.metal...
// Compile options as bench: language 4.0, mathMode safe, precise functions. Entry point names are fixed (main0).
//  vs: real vertex shader + synthetic fragment. -fs trivial: reads nothing; -fs full (default): reads every user
//      output of main0_out, so the linker cannot drop any. Vertex descriptor from the reflected vertexAttributes.
//  cs: MTLComputePipelineDescriptor, addComputePipelineFunctions.
//  ms: MTLMeshRenderPipelineDescriptor, real mesh + synthetic fragment (-fs as above, over spvPerVertex and
//      spvPerPrimitive user fields); -obj syn adds a synthetic object shader that fills the payload type.
//  os: real object shader + synthetic mesh (takes its payload, emits nothing) + trivial fragment.
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { Double(b - a) / 1e6 }

var args = Array(CommandLine.arguments.dropFirst())
var jobs = 1, quiet = false, archiveDir: String? = nil, stage = "", fsMode = "full", objMode = "none"
while let a = args.first, a.hasPrefix("-") {
    args.removeFirst()
    switch a {
    case "-j": jobs = Int(args.removeFirst())!
    case "-q": quiet = true
    case "-archivedir": archiveDir = args.removeFirst()
    case "-stage": stage = args.removeFirst()
    case "-fs": fsMode = args.removeFirst()
    case "-obj": objMode = args.removeFirst()
    default: fatalError("bad flag \(a)")
    }
}
precondition(["vs", "cs", "ms", "os"].contains(stage), "need -stage vs|cs|ms|os")
let dev = MTLCreateSystemDefaultDevice()!
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = .version4_0
    o.mathMode = .safe
    o.mathFloatingPointFunctions = .precise
    return o
}
_ = try! dev.makeLibrary(source: "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }", options: nil)

func structBody(_ src: String, _ name: String) -> String? {
    guard let r = src.range(of: "struct \(name)\n{") ?? src.range(of: "struct \(name) {") ?? src.range(of: "struct \(name)\r\n{") else { return nil }
    guard let e = src.range(of: "};", range: r.upperBound..<src.endIndex) else { return nil }
    return String(src[r.upperBound..<e.lowerBound])
}
// user fields: "float4 name [[user(locnN)]];"
let userRe = try! NSRegularExpression(pattern: #"(\w+)\s+(\w+)\s*\[\[user\((locn\d+)\)\]\]"#)
func userFields(_ body: String) -> [(String, String, String)] {
    userRe.matches(in: body, range: NSRange(body.startIndex..., in: body)).map {
        (String(body[Range($0.range(at: 1), in: body)!]), String(body[Range($0.range(at: 2), in: body)!]), String(body[Range($0.range(at: 3), in: body)!]))
    }
}
func fragSource(_ fields: [(String, String, String)]) -> String {
    var s = "#include <metal_stdlib>\nusing namespace metal;\n"
    if fsMode == "trivial" || fields.isEmpty {
        return s + "fragment float4 synF() { return float4(1.0); }\n"
    }
    s += "struct FI {\n"
    for (i, f) in fields.enumerated() { s += "  \(f.0) f\(i) [[user(\(f.2))]];\n" }
    s += "};\nfragment float4 synF(FI i [[stage_in]]) {\n  float4 r = float4(0.0);\n"
    for (k, f) in fields.enumerated() { s += f.0.hasSuffix("4") ? "  r += float4(i.f\(k));\n" : "  r += float4(float(i.f\(k)));\n" }
    return s + "  return r;\n}\n"
}
let payloadRe = try! NSRegularExpression(pattern: #"object_data spvUnsafeArray<(\w+), (\d+)>&\s*\w+\s*\[\[payload\]\]"#)
func payload(_ src: String) -> (String, Int)? {
    guard let m = payloadRe.firstMatch(in: src, range: NSRange(src.startIndex..., in: src)) else { return nil }
    return (String(src[Range(m.range(at: 1), in: src)!]), Int(src[Range(m.range(at: 2), in: src)!])!)
}

func vertexDescriptor(_ fn: MTLFunction) -> MTLVertexDescriptor? {
    let vd = MTLVertexDescriptor()
    var offset = 0
    for a in fn.vertexAttributes ?? [] where a.isActive {
        let f: MTLVertexFormat
        switch a.attributeType {
        case .float: f = .float
        case .float2: f = .float2
        case .float3: f = .float3
        case .float4: f = .float4
        case .int: f = .int
        case .uint: f = .uint
        case .int2: f = .int2
        case .int3: f = .int3
        case .int4: f = .int4
        case .uint2: f = .uint2
        case .uint3: f = .uint3
        case .uint4: f = .uint4
        case .half: f = .half
        case .half2: f = .half2
        case .half3: f = .half3
        case .half4: f = .half4
        default: f = .float4
        }
        vd.attributes[a.attributeIndex].format = f
        vd.attributes[a.attributeIndex].offset = offset
        vd.attributes[a.attributeIndex].bufferIndex = 30
        offset += 16
    }
    if offset == 0 { return nil }
    vd.layouts[30].stride = offset
    return vd
}

struct Result { var lib = 0.0, pipe = 0.0, err: String? = nil }

func one(_ path: String) -> Result {
    var r = Result()
    let src = try! String(contentsOfFile: path, encoding: .utf8)
    do {
        let t0 = now()
        let lib = try dev.makeLibrary(source: src, options: options())
        r.lib = ms(t0, now())
        guard let fn = lib.makeFunction(name: "main0") else { throw NSError(domain: "no main0", code: 1) }
        let ar = try dev.makeBinaryArchive(descriptor: MTLBinaryArchiveDescriptor())
        let t1 = now()
        switch stage {
        case "cs":
            let d = MTLComputePipelineDescriptor()
            d.computeFunction = fn
            try ar.addComputePipelineFunctions(descriptor: d)
        case "vs":
            let fields = userFields(structBody(src, "main0_out") ?? "")
            let fl = try dev.makeLibrary(source: fragSource(fields), options: options())
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = fn
            d.fragmentFunction = fl.makeFunction(name: "synF")!
            d.vertexDescriptor = vertexDescriptor(fn)
            d.colorAttachments[0].pixelFormat = .rgba16Float
            d.depthAttachmentPixelFormat = .depth32Float
            try ar.addRenderPipelineFunctions(descriptor: d)
        case "ms":
            let fields = userFields(structBody(src, "spvPerVertex") ?? "") + userFields(structBody(src, "spvPerPrimitive") ?? "")
            var fsrc = fragSource(fields)
            let pl = payload(src)
            if objMode == "syn", let (ty, n) = pl {
                fsrc += "struct SP { \(ty) d[\(n)]; };\n[[object]] void synO(object_data SP& p [[payload]], mesh_grid_properties mgp, uint t [[thread_index_in_threadgroup]]) {\n"
                    + "  p.d[t % \(n)] = \(ty)(t);\n  if (t == 0) mgp.set_threadgroups_per_grid(uint3(1));\n}\n"
            }
            let fl = try dev.makeLibrary(source: fsrc, options: options())
            let d = MTLMeshRenderPipelineDescriptor()
            d.meshFunction = fn
            d.fragmentFunction = fl.makeFunction(name: "synF")!
            if objMode == "syn", let (_, n) = pl {
                d.objectFunction = fl.makeFunction(name: "synO")!
                d.payloadMemoryLength = n * 4
            }
            d.colorAttachments[0].pixelFormat = .rgba16Float
            d.depthAttachmentPixelFormat = .depth32Float
            try ar.addMeshRenderPipelineFunctions(descriptor: d)
        case "os":
            guard let (ty, n) = payload(src) else { throw NSError(domain: "no payload", code: 1) }
            let msrc = "#include <metal_stdlib>\nusing namespace metal;\nstruct SP { \(ty) d[\(n)]; };\n"
                + "struct SV { float4 pos [[position]]; };\n"
                + "[[mesh]] void synM(mesh<SV, void, 3, 1, topology::triangle> m, const object_data SP& p [[payload]], uint t [[thread_index_in_threadgroup]]) {\n"
                + "  if (t == 0) m.set_primitive_count(p.d[0] > 0 ? 0 : 0);\n}\n"
                + "fragment float4 synF() { return float4(1.0); }\n"
            let ml = try dev.makeLibrary(source: msrc, options: options())
            let d = MTLMeshRenderPipelineDescriptor()
            d.objectFunction = fn
            d.meshFunction = ml.makeFunction(name: "synM")!
            d.fragmentFunction = ml.makeFunction(name: "synF")!
            d.payloadMemoryLength = n * 4
            d.colorAttachments[0].pixelFormat = .rgba16Float
            d.depthAttachmentPixelFormat = .depth32Float
            try ar.addMeshRenderPipelineFunctions(descriptor: d)
        default: break
        }
        r.pipe = ms(t1, now())
        if let dir = archiveDir {
            let ap = dir + "/" + (path as NSString).lastPathComponent + ".bin"
            try? FileManager.default.removeItem(atPath: ap)
            try ar.serialize(to: URL(fileURLWithPath: ap))
        }
    } catch { r.err = String("\(error)".prefix(400)).replacingOccurrences(of: "\n", with: " | ") }
    return r
}

let lock = NSLock()
var sumLib = 0.0, sumPipe = 0.0, failed = 0
let t0 = now()
let q = OperationQueue(); q.maxConcurrentOperationCount = jobs
for p in args {
    q.addOperation {
        let r = one(p)
        lock.lock()
        if let e = r.err { failed += 1; print("FAIL \((p as NSString).lastPathComponent): \(e)") }
        else {
            sumLib += r.lib; sumPipe += r.pipe
            if !quiet { print(String(format: "%@ lib=%.1f pipe=%.1f", (p as NSString).lastPathComponent, r.lib, r.pipe)) }
        }
        lock.unlock()
    }
}
q.waitUntilAllOperationsAreFinished()
print(String(format: "TOTAL stage=%@ files=%d jobs=%d failed=%d wall=%.0f ms sum(lib)=%.0f sum(pipe)=%.0f",
             stage, args.count, jobs, failed, ms(t0, now()), sumLib, sumPipe))
