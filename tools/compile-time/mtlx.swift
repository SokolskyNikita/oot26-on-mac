// mtlx: cold-compile timings for a vertex + fragment MSL pair, with variants.
// Usage: mtlx [--reps N] [--opt size] [--inv] [--lang 3.2] [--mode safe|relaxed|fast] [--par] [--pipe2] VS.metal FS.metal
//        mtlx [--reps N] [options] --libonly FILE...
// Every repetition renames the entry point "main0" to a fresh name, so neither Metal's library cache nor its
// pipeline cache can answer. Prints the median and minimum over the repetitions, in ms.
//   vlib/flib  MTLDevice.makeLibrary(source:)            (MSL -> AIR)
//   pipe       makeRenderPipelineState                   (AIR -> GPU code)
//   --pipe2    then three more pipelines from the SAME functions: blending on, bgra8 attachment, no depth
//   --par      compiles the two libraries concurrently and reports the wall time as "par"
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func msSince(_ t: UInt64) -> Double { Double(now() - t) / 1e6 }

var reps = 3, optSize = false, inv = false, lang = MTLLanguageVersion.version4_0, mode = "safe"
var par = false, pipe2 = false, libonly = false
var files: [String] = []
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    switch a {
    case "--reps": reps = Int(it.next()!)!
    case "--opt": optSize = it.next()! == "size"
    case "--inv": inv = true
    case "--lang": lang = it.next()! == "3.2" ? .version3_2 : .version4_0
    case "--mode": mode = it.next()!
    case "--par": par = true
    case "--pipe2": pipe2 = true
    case "--libonly": libonly = true
    default: files.append(a)
    }
}
let dev = MTLCreateSystemDefaultDevice()!
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = lang
    o.mathMode = mode == "fast" ? .fast : mode == "relaxed" ? .relaxed : .safe
    o.mathFloatingPointFunctions = mode == "fast" ? .fast : .precise
    o.preserveInvariance = inv
    if optSize { o.optimizationLevel = .size }
    return o
}
func fresh(_ src: String) -> String {
    src.replacingOccurrences(of: "main0", with: "m\(UInt32.random(in: 0 ..< UInt32.max))x")
}
func compile(_ src: String) -> (MTLLibrary, Double) {
    let t = now()
    let lib = try! dev.makeLibrary(source: src, options: options())
    return (lib, msSince(t))
}
func stat(_ name: String, _ v: [Double]) -> String {
    guard !v.isEmpty else { return "" }
    let s = v.sorted()
    return String(format: "%@ med %.1f min %.1f", name, s[s.count / 2], s[0])
}

if libonly {
    for f in files {
        let src = try! String(contentsOfFile: f, encoding: .utf8)
        var t: [Double] = []
        for _ in 0 ..< reps { t.append(compile(fresh(src)).1) }
        print("\((f as NSString).lastPathComponent) (\(src.utf8.count) B): \(stat("lib", t))")
    }
    exit(0)
}

let vsrc0 = try! String(contentsOfFile: files[0], encoding: .utf8)
let fsrc0 = try! String(contentsOfFile: files[1], encoding: .utf8)
var tv: [Double] = [], tf: [Double] = [], tp: [Double] = [], tpar: [Double] = []
var t2: [[Double]] = [[], [], [], [], [], []]
for _ in 0 ..< reps {
    let vsrc = fresh(vsrc0), fsrc = fresh(fsrc0)
    var vlib: MTLLibrary!, flib: MTLLibrary!
    if par {
        let t = now()
        DispatchQueue.concurrentPerform(iterations: 2) { i in
            if i == 0 { vlib = compile(vsrc).0 } else { flib = compile(fsrc).0 }
        }
        tpar.append(msSince(t))
    } else {
        let a = compile(vsrc), b = compile(fsrc)
        vlib = a.0; flib = b.0; tv.append(a.1); tf.append(b.1)
    }
    let vfn = vlib.functionNames.compactMap { vlib.makeFunction(name: $0) }.first { $0.functionType == .vertex }!
    let ffn = flib.functionNames.compactMap { flib.makeFunction(name: $0) }.first { $0.functionType == .fragment }!
    let d = MTLRenderPipelineDescriptor()
    d.vertexFunction = vfn
    d.fragmentFunction = ffn
    let vd = MTLVertexDescriptor()
    var offset = 0
    for a in vfn.vertexAttributes ?? [] where a.isActive {
        vd.attributes[a.attributeIndex].format = .float4
        vd.attributes[a.attributeIndex].offset = offset
        vd.attributes[a.attributeIndex].bufferIndex = 30
        offset += 16
    }
    if offset > 0 { vd.layouts[30].stride = offset; d.vertexDescriptor = vd }
    let re = try! NSRegularExpression(pattern: #"(\w+)\s+\w+\s*\[\[color\((\d+)\)"#)
    for m in re.matches(in: fsrc, range: NSRange(fsrc.startIndex..., in: fsrc)) {
        let ty = String(fsrc[Range(m.range(at: 1), in: fsrc)!])
        let idx = Int(fsrc[Range(m.range(at: 2), in: fsrc)!])!
        d.colorAttachments[idx].pixelFormat = ty.hasPrefix("uint") ? .rgba32Uint : ty.hasPrefix("int") ? .rgba32Sint : .rgba16Float
    }
    d.depthAttachmentPixelFormat = .depth32Float
    func build() -> Double {
        let t = now()
        do { _ = try dev.makeRenderPipelineState(descriptor: d, options: [], reflection: nil) }
        catch { print("PIPELINE ERROR: \(error.localizedDescription.prefix(400))"); exit(1) }
        return msSince(t)
    }
    tp.append(build())
    if pipe2 {
        d.colorAttachments[0].isBlendingEnabled = true
        d.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
        d.colorAttachments[0].destinationRGBBlendFactor = .oneMinusSourceAlpha
        t2[0].append(build())
        d.colorAttachments[0].pixelFormat = .bgra8Unorm
        t2[1].append(build())
        d.depthAttachmentPixelFormat = .invalid
        t2[2].append(build())
        // back to the first descriptor, then vary only vertex-side state
        d.depthAttachmentPixelFormat = .depth32Float
        d.colorAttachments[0].pixelFormat = .rgba16Float
        d.colorAttachments[0].isBlendingEnabled = false
        t2[3].append(build())                       // identical to the first pipeline
        vd.layouts[30].stride = offset + 32
        d.vertexDescriptor = vd
        t2[4].append(build())                       // other vertex stride
        let vlib2 = compile(fresh(vsrc0)).0
        d.vertexFunction = vlib2.functionNames.compactMap { vlib2.makeFunction(name: $0) }.first { $0.functionType == .vertex }!
        t2[5].append(build())                       // other vertex function, same fragment function
    }
}
var parts = [stat("vlib", tv), stat("flib", tf), stat("par", tpar), stat("pipe", tp)]
if pipe2 { parts += [stat("+blend", t2[0]), stat("+bgra8", t2[1]), stat("+nodepth", t2[2]), stat("same again", t2[3]), stat("+stride", t2[4]), stat("+other VS", t2[5])] }
print(parts.filter { !$0.isEmpty }.joined(separator: " | "))
