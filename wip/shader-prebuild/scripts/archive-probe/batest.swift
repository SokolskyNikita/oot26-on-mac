// Standalone MTLBinaryArchive probe. Usage: batest <mode> <seed> <dir>
// modes: make (compile, collect into archive, serialise), noarch (control), arch (lookup from archive)
import Metal
import Foundation

func now() -> Double { Double(DispatchTime.now().uptimeNanoseconds) / 1e6 }
let args = CommandLine.arguments
let mode = args[1], seed = Int(args[2])!, dir = args[3]
let archURL = URL(fileURLWithPath: dir + "/archive-\(seed).bin")
let dev = MTLCreateSystemDefaultDevice()!

func source(_ seed: Int, extraComment: Bool = false) -> String {
    var s = "#include <metal_stdlib>\nusing namespace metal;\n"
    if extraComment { s += "// an extra comment that changes nothing\n" }
    s += "struct VIn { float4 pos [[attribute(0)]]; float4 col [[attribute(1)]]; };\n"
    s += "struct VOut { float4 pos [[position]]; float4 col; };\n"
    s += "vertex VOut vmain(VIn in [[stage_in]]) { VOut o; o.pos = in.pos; o.col = in.col * \(seed).0; return o; }\n"
    s += "fragment float4 fmain(VOut in [[stage_in]], texture2d<float> t [[texture(0)]], sampler sm [[sampler(0)]]) {\n float4 v = in.col;\n"
    for i in 0..<(Int(ProcessInfo.processInfo.environment["NSTMT"] ?? "600")!) {
        s += " v = sin(v * float4(\(i % 7 + 1).\(seed % 10)) + t.sample(sm, v.xy + float2(\(i).0)).zwxy) * cos(v.yzwx + \(i).5);\n"
        if i % 50 == 0 { s += " if (v.x > \(i).0) { v = sqrt(abs(v)) + v.wzyx; }\n" }
    }
    s += " return v; }\n"
    s += "kernel void kmain(device float* b [[buffer(0)]], uint i [[thread_position_in_grid]]) { b[i] = b[i] * \(seed).0 + 1.0; }\n"
    s += "struct MV { float4 pos [[position]]; };\n"
    s += "using MeshT = metal::mesh<MV, void, 3, 1, topology::triangle>;\n"
    s += "[[mesh]] void mmain(MeshT m, uint tid [[thread_index_in_threadgroup]]) { if (tid == 0) { m.set_primitive_count(1); m.set_index(0,0); m.set_index(1,1); m.set_index(2,2); } if (tid < 3) { MV v; v.pos = float4(float(tid), \(seed).0, 0, 1); m.set_vertex(tid, v); } }\n"
    s += "fragment float4 mfrag(MV in [[stage_in]]) { return in.pos; }\n"
    return s
}

func lib(_ src: String) -> (MTLLibrary, Double) {
    let t = now()
    let l = try! dev.makeLibrary(source: src, options: MTLCompileOptions())
    return (l, now() - t)
}

func renderDesc(_ l: MTLLibrary, stride: Int = 32, depth: MTLPixelFormat = .invalid, blend: Bool = false, label: String? = nil) -> MTLRenderPipelineDescriptor {
    let d = MTLRenderPipelineDescriptor()
    d.vertexFunction = l.makeFunction(name: "vmain")
    d.fragmentFunction = l.makeFunction(name: "fmain")
    d.colorAttachments[0].pixelFormat = .bgra8Unorm
    d.colorAttachments[0].isBlendingEnabled = blend
    d.depthAttachmentPixelFormat = depth
    let vd = MTLVertexDescriptor()
    vd.attributes[0].format = .float4; vd.attributes[0].offset = 0; vd.attributes[0].bufferIndex = 0
    vd.attributes[1].format = .float4; vd.attributes[1].offset = 16; vd.attributes[1].bufferIndex = 0
    vd.layouts[0].stride = stride
    d.vertexDescriptor = vd
    if let label = label { d.label = label }
    return d
}
func computeDesc(_ l: MTLLibrary) -> MTLComputePipelineDescriptor {
    let d = MTLComputePipelineDescriptor(); d.computeFunction = l.makeFunction(name: "kmain"); return d
}
func meshDesc(_ l: MTLLibrary) -> MTLMeshRenderPipelineDescriptor {
    let d = MTLMeshRenderPipelineDescriptor()
    d.meshFunction = l.makeFunction(name: "mmain"); d.fragmentFunction = l.makeFunction(name: "mfrag")
    d.colorAttachments[0].pixelFormat = .bgra8Unorm
    return d
}

func timeRender(_ d: MTLRenderPipelineDescriptor, _ opt: MTLPipelineOption) -> (Bool, Double, String) {
    let t = now()
    do { _ = try dev.makeRenderPipelineState(descriptor: d, options: opt); return (true, now() - t, "") }
    catch { return (false, now() - t, "\(error.localizedDescription)") }
}
func timeCompute(_ d: MTLComputePipelineDescriptor, _ opt: MTLPipelineOption) -> (Bool, Double, String) {
    let t = now()
    do { _ = try dev.makeComputePipelineState(descriptor: d, options: opt); return (true, now() - t, "") }
    catch { return (false, now() - t, "\(error.localizedDescription)") }
}
func timeMesh(_ d: MTLMeshRenderPipelineDescriptor, _ opt: MTLPipelineOption) -> (Bool, Double, String) {
    let t = now()
    do { _ = try dev.makeRenderPipelineState(descriptor: d, options: opt); return (true, now() - t, "") }
    catch { return (false, now() - t, "\(error.localizedDescription)") }
}
func p(_ k: String, _ v: Any) { print("\(mode) seed=\(seed) \(k): \(v)") }
func r(_ x: (Bool, Double, String)) -> String { String(format: "%@ %.1f ms %@", x.0 ? "ok" : "FAIL", x.1, x.2) }

print("device: \(dev.name), env MTL_SHADER_CACHE_SIZE=\(ProcessInfo.processInfo.environment["MTL_SHADER_CACHE_SIZE"] ?? "unset")")
let (l, lt) = lib(source(seed))
p("library from MSL", String(format: "%.1f ms", lt))

switch mode {
case "make":
    p("render pipeline (compile)", r(timeRender(renderDesc(l), [])))
    p("compute pipeline (compile)", r(timeCompute(computeDesc(l), [])))
    p("mesh pipeline (compile)", r(timeMesh(meshDesc(l), [])))
    let ad = MTLBinaryArchiveDescriptor()
    let a = try! dev.makeBinaryArchive(descriptor: ad)
    var t = now(); try! a.addRenderPipelineFunctions(descriptor: renderDesc(l)); p("archive add render", String(format: "%.1f ms", now() - t))
    t = now(); try! a.addComputePipelineFunctions(descriptor: computeDesc(l)); p("archive add compute", String(format: "%.1f ms", now() - t))
    t = now()
    do { try a.addMeshRenderPipelineFunctions(descriptor: meshDesc(l)); p("archive add mesh", String(format: "ok %.1f ms", now() - t)) }
    catch { p("archive add mesh", "FAIL \(error)") }
    t = now(); try! a.serialize(to: archURL); p("serialise", String(format: "%.1f ms", now() - t))
    let sz = (try! FileManager.default.attributesOfItem(atPath: archURL.path)[.size] as! NSNumber).intValue
    p("archive bytes", sz)
    // Can the archive file be opened as a library (does it carry AIR / reusable library code)?
    do { let l2 = try dev.makeLibrary(URL: archURL); p("archive as MTLLibrary", "opened, functions: \(l2.functionNames)") }
    catch { p("archive as MTLLibrary", "refused: \(error.localizedDescription)") }
    // Can a dynamic library hold render entry points (to serialise compiled library code)?
    let o = MTLCompileOptions(); o.libraryType = .dynamic; o.installName = "@executable_path/x.metallib"
    do { let dl = try dev.makeLibrary(source: source(seed), options: o); let dy = try dev.makeDynamicLibrary(library: dl); p("dynamic library with vertex/fragment", "made: \(dy.installName)") }
    catch { p("dynamic library with vertex/fragment", "refused: \(error.localizedDescription)") }
case "noarch":
    p("render pipeline (no archive)", r(timeRender(renderDesc(l), [])))
    p("compute pipeline (no archive)", r(timeCompute(computeDesc(l), [])))
    p("mesh pipeline (no archive)", r(timeMesh(meshDesc(l), [])))
case "arch":
    let ad = MTLBinaryArchiveDescriptor(); ad.url = archURL
    let t = now(); let a = try! dev.makeBinaryArchive(descriptor: ad); p("archive load", String(format: "%.2f ms", now() - t))
    func withA<D>(_ d: D) -> D { (d as AnyObject).setValue([a], forKey: "binaryArchives"); return d }
    let strict: MTLPipelineOption = .failOnBinaryArchiveMiss
    p("render from archive (strict)", r(timeRender(withA(renderDesc(l)), strict)))
    p("compute from archive (strict)", r(timeCompute(withA(computeDesc(l)), strict)))
    p("mesh from archive (strict)", r(timeMesh(withA(meshDesc(l)), strict)))
    p("variant: other label (strict)", r(timeRender(withA(renderDesc(l, label: "x")), strict)))
    p("variant: depth format added (strict)", r(timeRender(withA(renderDesc(l, depth: .depth32Float)), strict)))
    p("variant: vertex stride 48 (strict)", r(timeRender(withA(renderDesc(l, stride: 48)), strict)))
    p("variant: blending on (strict)", r(timeRender(withA(renderDesc(l, blend: true)), strict)))
    let (l3, lt3) = lib(source(seed, extraComment: true))
    p("library from MSL with one extra comment", String(format: "%.1f ms", lt3))
    p("variant: library from source with extra comment (strict)", r(timeRender(withA(renderDesc(l3)), strict)))
case "fromfile":
    // Library loaded from the serialised archive file instead of compiled from MSL
    var t = now(); let lf = try! dev.makeLibrary(URL: archURL); p("library from archive file (makeLibrary URL)", String(format: "%.2f ms, functions %d", now() - t, lf.functionNames.count))
    let data = try! Data(contentsOf: archURL)
    t = now(); let ld = try! dev.makeLibrary(data: data.withUnsafeBytes { DispatchData(bytes: $0) } as __DispatchData); p("library from archive bytes (makeLibrary data)", String(format: "%.2f ms", now() - t))
    _ = ld
    let ad = MTLBinaryArchiveDescriptor(); ad.url = archURL
    let a = try! dev.makeBinaryArchive(descriptor: ad)
    func withA<D>(_ d: D) -> D { (d as AnyObject).setValue([a], forKey: "binaryArchives"); return d }
    p("render from archive, functions of file library (strict)", r(timeRender(withA(renderDesc(lf)), .failOnBinaryArchiveMiss)))
    p("render without archive, functions of file library", r(timeRender(renderDesc(lf), [])))
case "dup":
    // Two libraries with the same entry-point names in one archive; add-first then create from the in-memory archive
    let (l2, _) = lib(source(seed + 1))
    let a = try! dev.makeBinaryArchive(descriptor: MTLBinaryArchiveDescriptor())
    var t = now(); try! a.addRenderPipelineFunctions(descriptor: renderDesc(l)); p("add first (lib A)", String(format: "%.1f ms", now() - t))
    t = now(); try! a.addRenderPipelineFunctions(descriptor: renderDesc(l2)); p("add first (lib B)", String(format: "%.1f ms", now() - t))
    func withA<D>(_ d: D) -> D { (d as AnyObject).setValue([a], forKey: "binaryArchives"); return d }
    p("create A from in-memory archive (strict)", r(timeRender(withA(renderDesc(l)), .failOnBinaryArchiveMiss)))
    let u = URL(fileURLWithPath: dir + "/dup-\(seed).bin"); try! a.serialize(to: u)
    let lf = try! dev.makeLibrary(URL: u); p("dup archive as library: function names", lf.functionNames.sorted())
    let a2 = try! dev.makeBinaryArchive(descriptor: { let d = MTLBinaryArchiveDescriptor(); d.url = u; return d }())
    func withB<D>(_ d: D) -> D { (d as AnyObject).setValue([a2], forKey: "binaryArchives"); return d }
    p("reloaded: A (strict)", r(timeRender(withB(renderDesc(l)), .failOnBinaryArchiveMiss)))
    p("reloaded: B (strict)", r(timeRender(withB(renderDesc(l2)), .failOnBinaryArchiveMiss)))
    p("reloaded: functions of file library (strict)", r(timeRender(withB(renderDesc(lf)), .failOnBinaryArchiveMiss)))
case "fileonly":
    // Fresh process: library from the archive file, pipeline WITHOUT binaryArchives set
    var t = now(); let lf = try! dev.makeLibrary(URL: archURL); p("library from archive file", String(format: "%.2f ms", now() - t))
    p("render, file library, no archive (first in process)", r(timeRender(renderDesc(lf), [])))
    p("render, file library, no archive, stride 48 (state not in archive)", r(timeRender(renderDesc(lf, stride: 48), [])))
case "bytesonly":
    let data = try! Data(contentsOf: archURL)
    var t = now(); let ld = try! dev.makeLibrary(data: data.withUnsafeBytes { DispatchData(bytes: $0) } as __DispatchData); p("library from archive bytes", String(format: "%.2f ms", now() - t))
    p("render, bytes library, no archive (first in process)", r(timeRender(renderDesc(ld), [])))
case "addfunc":
    // Can a library alone (vertex/fragment functions, no pipeline) be put in an archive and read back as a library?
    let a = try! dev.makeBinaryArchive(descriptor: MTLBinaryArchiveDescriptor())
    for fn in ["vmain", "fmain"] {
        let fd = MTLFunctionDescriptor(); fd.name = fn
        let t = now()
        do { try a.addFunction(descriptor: fd, library: l); p("addFunction \(fn)", String(format: "ok %.1f ms", now() - t)) }
        catch { p("addFunction \(fn)", "refused: \(error.localizedDescription)") }
    }
    let u = URL(fileURLWithPath: dir + "/libonly-\(seed).bin")
    do { try a.serialize(to: u); let lf = try dev.makeLibrary(URL: u); p("library-only archive as library", "\(lf.functionNames) bytes \((try! FileManager.default.attributesOfItem(atPath: u.path)[.size] as! NSNumber).intValue)") }
    catch { p("library-only archive", "failed: \(error.localizedDescription)") }
default: break
}
