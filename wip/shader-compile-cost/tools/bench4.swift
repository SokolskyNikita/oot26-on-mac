// bench4: cold compile timing of fragment MSL through the Metal 4 compiler (MTL4Compiler), next to the old path.
// Usage: MTL_SHADER_CACHE_SIZE=0 bench4 [flags] FS.metal...
// Per file: compiler.makeLibrary(descriptor:) (MSL -> AIR) and compiler.makeRenderPipelineState(descriptor:) (AIR -> GPU
// code), with the same synthetic vertex shader, compile options and colour formats as ../bench.swift. Each compile
// gets a fresh entry-point name so nothing is reused.
// Flags:
//   -j N           N concurrent compiles (OperationQueue), wall time reported
//   -reps R        repeat the file list R times
//   -q             only the TOTAL line
//   -old           use the old path (device.makeLibrary / device.makeRenderPipelineState) inside this tool
//   -async         use the completion-handler API (compiler tasks) instead of the blocking calls; -j caps in-flight tasks
//   -maxconc       MTL4CompilerDescriptor.shouldMaximizeConcurrentCompilation = true (private property, KVC)
//   -devmax        MTLDevice.shouldMaximizeConcurrentCompilation = true
//   -qos NAME      run the compiles at QoS ui|init|default|utility|bg (OperationQueue.qualityOfService)
//   -percomp       one MTL4Compiler per compile instead of one shared compiler
//   -ser N         attach a MTL4PipelineDataSetSerializer with configuration N (1 descriptors, 2 binaries, 3 both)
//   -lookup PATH   pass this MTL4Archive as compilerTaskOptions.lookupArchives
//   -harvest PATH  with -ser 2/3: write the serializer's archive to PATH at the end
//   -fixedname     keep main0 (for archive hit tests)
//   -libname       set MTL4LibraryDescriptor.name
//   -kv K=V        MTLCompileOptions key (KVC)
//   -plkv K=V      MTL4PipelineOptions key (KVC), on the pipeline descriptor
//   -pdkv K=V      MTL4RenderPipelineDescriptor / MTL4PipelineDescriptor key (KVC)
//   -reflect N     MTL4PipelineOptions.shaderReflection raw value
//   -blend N       MTL4RenderPipelineColorAttachmentDescriptor.blendingState raw value (0 off, 1 on, 2 unspecialized)
//   -opt size      MTLCompileOptions.optimizationLevel = .size
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { Double(b - a) / 1e6 }
func val(_ v: String) -> Any { v == "true" ? true : v == "false" ? false : (Int(v) as Any? ?? v) }
func kvpair(_ s: String) -> (String, String) { let p = s.split(separator: "=", maxSplits: 1); return (String(p[0]), String(p[1])) }

var args = Array(CommandLine.arguments.dropFirst())
var jobs = 1, reps = 1, quiet = false, old = false, async = false, maxconc = false, devmax = false, qos: QualityOfService? = nil
var percomp = false, serCfg: UInt? = nil, lookupPath: String? = nil, harvestPath: String? = nil, fixedName = false, libName = false
var blend: Int? = nil
var kv: [(String, String)] = [], plkv: [(String, String)] = [], pdkv: [(String, String)] = [], reflect: UInt? = nil, optSize = false
while let a = args.first, a.hasPrefix("-") {
    args.removeFirst()
    switch a {
    case "-j": jobs = Int(args.removeFirst())!
    case "-reps": reps = Int(args.removeFirst())!
    case "-q": quiet = true
    case "-old": old = true
    case "-async": async = true
    case "-maxconc": maxconc = true
    case "-devmax": devmax = true
    case "-qos": qos = ["ui": .userInteractive, "init": .userInitiated, "default": .default, "utility": .utility, "bg": .background][args.removeFirst()]!
    case "-percomp": percomp = true
    case "-ser": serCfg = UInt(args.removeFirst())!
    case "-lookup": lookupPath = args.removeFirst()
    case "-harvest": harvestPath = args.removeFirst()
    case "-fixedname": fixedName = true
    case "-libname": libName = true
    case "-kv": kv.append(kvpair(args.removeFirst()))
    case "-plkv": plkv.append(kvpair(args.removeFirst()))
    case "-pdkv": pdkv.append(kvpair(args.removeFirst()))
    case "-reflect": reflect = UInt(args.removeFirst())!
    case "-blend": blend = Int(args.removeFirst())!
    case "-opt": optSize = args.removeFirst() == "size"
    default: fatalError("bad flag \(a)")
    }
}
let dev = MTLCreateSystemDefaultDevice()!
if devmax { dev.shouldMaximizeConcurrentCompilation = true }
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = .version4_0
    o.mathMode = .safe; o.mathFloatingPointFunctions = .precise
    if optSize { o.optimizationLevel = .size }
    for (k, v) in kv { o.setValue(val(v), forKey: k) }
    return o
}
var serializer: MTL4PipelineDataSetSerializer? = nil
if let c = serCfg {
    let sd = MTL4PipelineDataSetSerializerDescriptor()
    sd.configuration = MTL4PipelineDataSetSerializerConfiguration(rawValue: c)
    serializer = dev.makePipelineDataSetSerializer(descriptor: sd)
}
func makeCompiler() -> MTL4Compiler {
    let cd = MTL4CompilerDescriptor()
    if maxconc { cd.setValue(true, forKey: "shouldMaximizeConcurrentCompilation") }
    if let s = serializer { cd.pipelineDataSetSerializer = s }
    do { return try dev.makeCompiler(descriptor: cd) } catch { fatalError("makeCompiler failed: \(error)") }
}
let shared = makeCompiler()
var taskOpts: MTL4CompilerTaskOptions? = nil
if let lp = lookupPath {
    do { let ar = try dev.makeArchive(url: URL(fileURLWithPath: lp)); let t = MTL4CompilerTaskOptions(); t.lookupArchives = [ar]; taskOpts = t }
    catch { fatalError("makeArchive(\(lp)) failed: \(error)") }
}
// Warm the front end once, as bench.swift does, so process start-up is not charged to the first file.
_ = try! dev.makeLibrary(source: "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }", options: nil)
if !old {
    let ld = MTL4LibraryDescriptor(); ld.source = "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }"
    _ = try! shared.makeLibrary(descriptor: ld)
}

let inRe = try! NSRegularExpression(pattern: #"struct main0_in\s*\{([^}]*)\}"#)
let colRe = try! NSRegularExpression(pattern: #"(\w+)\s+\w+\s*\[\[color\((\d+)\)"#)

struct Result { var lib = 0.0, pipe = 0.0, bytes = 0, err: String? = nil }

struct Prepared { var n: String; var src: String; var vsrc: String; var cols: [(Int, MTLPixelFormat)]; var bytes: Int }
func prepare(_ path: String) -> Prepared {
    let src0 = try! String(contentsOfFile: path, encoding: .utf8)
    let n = fixedName ? "main0" : "m\(UInt32.random(in: 0..<UInt32.max))x"
    let src = src0.replacingOccurrences(of: "main0", with: n)
    var fields = ""
    if let m = inRe.firstMatch(in: src0, range: NSRange(src0.startIndex..., in: src0)) {
        fields = String(src0[Range(m.range(at: 1), in: src0)!])
    }
    let vsrc = "#include <metal_stdlib>\nusing namespace metal;\nstruct VO { float4 pos [[position]]; \(fields) };\n"
        + "vertex VO \(n)v(uint vid [[vertex_id]]) { VO o = {}; o.pos = float4(float(vid)); return o; }\n"
    var cols: [(Int, MTLPixelFormat)] = []
    for m in colRe.matches(in: src0, range: NSRange(src0.startIndex..., in: src0)) {
        let ty = String(src0[Range(m.range(at: 1), in: src0)!])
        let idx = Int(src0[Range(m.range(at: 2), in: src0)!])!
        cols.append((idx, ty.hasPrefix("uint") ? .rgba32Uint : ty.hasPrefix("int") ? .rgba32Sint : .rgba16Float))
    }
    return Prepared(n: n, src: src, vsrc: vsrc, cols: cols, bytes: src0.utf8.count)
}

func oneOld(_ p: Prepared) -> Result {
    var r = Result(); r.bytes = p.bytes
    do {
        let vl = try dev.makeLibrary(source: p.vsrc, options: options())
        let t0 = now()
        let fl = try dev.makeLibrary(source: p.src, options: options())
        r.lib = ms(t0, now())
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = vl.makeFunction(name: p.n + "v")!
        d.fragmentFunction = fl.makeFunction(name: p.n)!
        for (i, f) in p.cols { d.colorAttachments[i].pixelFormat = f }
        d.depthAttachmentPixelFormat = .depth32Float
        let t2 = now()
        _ = try dev.makeRenderPipelineState(descriptor: d, options: [], reflection: nil)
        r.pipe = ms(t2, now())
    } catch { r.err = String("\(error)".prefix(300)) }
    return r
}

func libDesc(_ src: String, _ name: String) -> MTL4LibraryDescriptor {
    let ld = MTL4LibraryDescriptor(); ld.source = src; ld.options = options()
    if libName { ld.name = name }
    return ld
}
func pipeDesc(_ p: Prepared, _ vl: MTLLibrary, _ fl: MTLLibrary) -> MTL4RenderPipelineDescriptor {
    let d = MTL4RenderPipelineDescriptor()
    let vf = MTL4LibraryFunctionDescriptor(); vf.library = vl; vf.name = p.n + "v"
    let ff = MTL4LibraryFunctionDescriptor(); ff.library = fl; ff.name = p.n
    d.vertexFunctionDescriptor = vf; d.fragmentFunctionDescriptor = ff
    for (i, f) in p.cols { d.colorAttachments[i].pixelFormat = f; if let b = blend { d.colorAttachments[i].blendingState = MTL4BlendState(rawValue: b)! } }
    if !plkv.isEmpty || reflect != nil {
        let po = MTL4PipelineOptions()
        if let rf = reflect { po.shaderReflection = MTL4ShaderReflection(rawValue: rf) }
        for (k, v) in plkv { po.setValue(val(v), forKey: k) }
        d.options = po
    }
    for (k, v) in pdkv { d.setValue(val(v), forKey: k) }
    return d
}

func oneNew(_ p: Prepared) -> Result {
    var r = Result(); r.bytes = p.bytes
    let c = percomp ? makeCompiler() : shared
    do {
        let vl = try c.makeLibrary(descriptor: libDesc(p.vsrc, p.n + "vlib"))
        let t0 = now()
        let fl = try c.makeLibrary(descriptor: libDesc(p.src, p.n + "lib"))
        r.lib = ms(t0, now())
        let d = pipeDesc(p, vl, fl)
        let t2 = now()
        _ = try c.makeRenderPipelineState(descriptor: d, compilerTaskOptions: taskOpts)
        r.pipe = ms(t2, now())
    } catch { r.err = String("\(error)".prefix(300)) }
    return r
}

// Async path: the completion-handler methods are imported into Swift only as async (MTL4CompilerTask is
// NS_SWIFT_UNAVAILABLE), so this awaits them from a Swift Task. Times are await start -> resume.
func oneAsync(_ p: Prepared, _ done: @escaping @Sendable (Result) -> Void) {
    let c = percomp ? makeCompiler() : shared
    Task {
        var r = Result(); r.bytes = p.bytes
        do {
            let vl = try await c.makeLibrary(descriptor: libDesc(p.vsrc, p.n + "vlib"))
            let t0 = now()
            let fl = try await c.makeLibrary(descriptor: libDesc(p.src, p.n + "lib"))
            r.lib = ms(t0, now())
            let d = pipeDesc(p, vl, fl)
            let t2 = now()
            _ = try await c.makeRenderPipelineState(descriptor: d, dynamicLinkingDescriptor: nil, compilerTaskOptions: taskOpts)
            r.pipe = ms(t2, now())
        } catch { r.err = String("\(error)".prefix(300)) }
        done(r)
    }
}

let lock = NSLock()
var total = Result(), failed = 0
var libs: [Double] = [], pipes: [Double] = []
func record(_ path: String, _ r: Result) {
    lock.lock()
    if let e = r.err { failed += 1; if !quiet { print("FAIL \(path): \(e)") } }
    else {
        total.lib += r.lib; total.pipe += r.pipe; total.bytes += r.bytes; libs.append(r.lib); pipes.append(r.pipe)
        if !quiet { print(String(format: "%@ bytes=%d lib=%.1f pipe=%.1f", (path as NSString).lastPathComponent, r.bytes, r.lib, r.pipe)) }
    }
    lock.unlock()
}
// Inputs are read and prepared before the clock starts.
var work: [(String, Prepared)] = []
for _ in 0..<reps { for p in args { work.append((p, prepare(p))) } }
let t0 = now()
if async {
    let sem = DispatchSemaphore(value: jobs), g = DispatchGroup()
    for (path, p) in work {
        sem.wait(); g.enter()
        oneAsync(p) { r in record(path, r); sem.signal(); g.leave() }
    }
    g.wait()
} else {
    let q = OperationQueue(); q.maxConcurrentOperationCount = jobs
    if let qs = qos { q.qualityOfService = qs }
    for (path, p) in work { q.addOperation { record(path, old ? oneOld(p) : oneNew(p)) } }
    q.waitUntilAllOperationsAreFinished()
}
let wall = ms(t0, now())
if let hp = harvestPath, let s = serializer {
    do { try? FileManager.default.removeItem(atPath: hp); try s.serializeAsArchiveAndFlush(url: URL(fileURLWithPath: hp)); print("harvested -> \(hp)") }
    catch { print("serialize failed: \(error)") }
}
let n = Double(work.count - failed)
func med(_ a: [Double]) -> Double { let s = a.sorted(); return s.isEmpty ? 0 : s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2 }
let tot = zip(libs, pipes).map { $0 + $1 }
print(String(format: "TOTAL path=%@ files=%d reps=%d jobs=%d failed=%d wall=%.0f ms  mean lib=%.1f pipe=%.1f  min lib=%.1f pipe=%.1f tot=%.1f  med lib=%.1f pipe=%.1f tot=%.1f  wall/shader=%.1f ms  maxConcTasks=%d",
             old ? "old" : async ? "mtl4-async" : "mtl4", args.count, reps, jobs, failed, wall, total.lib / n, total.pipe / n,
             libs.min() ?? 0, pipes.min() ?? 0, tot.min() ?? 0, med(libs), med(pipes), med(tot), wall / n, dev.maximumConcurrentCompilationTaskCount))
