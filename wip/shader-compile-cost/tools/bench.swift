// bench: cold compile timing of fragment MSL, the way MoltenVK drives Metal.
// Usage: MTL_SHADER_CACHE_SIZE=0 bench [-j N] [-reps R] [-opt size] [-q] FS.metal...
// Per file: makeLibrary(source:) (MSL -> AIR) and makeRenderPipelineState (AIR -> GPU code), with a synthetic
// vertex shader that matches the fragment inputs. Each compile gets a fresh entry-point name so nothing is reused.
// -j N compiles the files on N threads and reports the wall time for the whole set.
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { Double(b - a) / 1e6 }

var args = Array(CommandLine.arguments.dropFirst())
var jobs = 1, reps = 1, quiet = false, optSize = false, libOnly = false, extraArgs: String? = nil, kv: [(String, String)] = [], forcedName: String? = nil, metallib: String? = nil, fixedName = false, forceMode = false, lang = MTLLanguageVersion.version4_0
let langs: [String: MTLLanguageVersion] = ["2_0": .version2_0, "2_2": .version2_2, "2_4": .version2_4, "3_0": .version3_0, "3_1": .version3_1, "3_2": .version3_2, "4_0": .version4_0]
while let a = args.first, a.hasPrefix("-") {
    args.removeFirst()
    switch a {
    case "-j": jobs = Int(args.removeFirst())!
    case "-reps": reps = Int(args.removeFirst())!
    case "-opt": optSize = args.removeFirst() == "size"
    case "-q": quiet = true
    case "-libonly": libOnly = true
    case "-args": extraArgs = args.removeFirst()
    case "-kv": let p = args.removeFirst().split(separator: "=", maxSplits: 1); kv.append((String(p[0]), String(p[1])))
    case "-name": forcedName = args.removeFirst()
    case "-metallib": metallib = args.removeFirst(); fixedName = true
    case "-fixedname": fixedName = true
    case "-mathmode": forceMode = true
    case "-lang": lang = langs[args.removeFirst()]!
    default: fatalError("bad flag \(a)")
    }
}
let dev = MTLCreateSystemDefaultDevice()!
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = lang
    if forceMode || lang.rawValue >= MTLLanguageVersion.version3_2.rawValue { o.mathMode = .safe; o.mathFloatingPointFunctions = .precise } else { o.fastMathEnabled = false }
    if optSize { o.optimizationLevel = .size }
    if let a = extraArgs { o.setValue(a, forKey: "additionalCompilerArguments") }
    for (k, v) in kv { o.setValue(v == "true" ? true : v == "false" ? false : (Int(v) as Any? ?? v), forKey: k) }
    return o
}
_ = try! dev.makeLibrary(source: "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }", options: nil)

let inRe = try! NSRegularExpression(pattern: #"struct main0_in\s*\{([^}]*)\}"#)
let colRe = try! NSRegularExpression(pattern: #"(\w+)\s+\w+\s*\[\[color\((\d+)\)"#)

struct Result { var lib = 0.0, pipe = 0.0, bytes = 0, err: String? = nil }

func one(_ path: String) -> Result {
    var r = Result()
    let src0 = try! String(contentsOfFile: path, encoding: .utf8)
    r.bytes = src0.utf8.count
    let n = forcedName != nil ? forcedName! : fixedName ? "main0" : "m\(UInt32.random(in: 0..<UInt32.max))x"
    let src = src0.replacingOccurrences(of: "main0", with: n)
    var fields = ""
    if let m = inRe.firstMatch(in: src0, range: NSRange(src0.startIndex..., in: src0)) {
        fields = String(src0[Range(m.range(at: 1), in: src0)!])
    }
    let vsrc = "#include <metal_stdlib>\nusing namespace metal;\nstruct VO { float4 pos [[position]]; \(fields) };\n"
        + "vertex VO \(n)v(uint vid [[vertex_id]]) { VO o = {}; o.pos = float4(float(vid)); return o; }\n"
    do {
        let vl = try dev.makeLibrary(source: vsrc, options: options())
        let t0 = now()
        let fl: MTLLibrary
        if let ml = metallib {
            let raw = try Data(contentsOf: URL(fileURLWithPath: ml))
            fl = try raw.withUnsafeBytes { try dev.makeLibrary(data: DispatchData(bytes: $0)) }
        } else { fl = try dev.makeLibrary(source: src, options: options()) }
        let t1 = now()
        r.lib = ms(t0, t1)
        if libOnly { return r }
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = vl.makeFunction(name: n + "v")!
        d.fragmentFunction = fl.makeFunction(name: n)!
        for m in colRe.matches(in: src0, range: NSRange(src0.startIndex..., in: src0)) {
            let ty = String(src0[Range(m.range(at: 1), in: src0)!])
            let idx = Int(src0[Range(m.range(at: 2), in: src0)!])!
            d.colorAttachments[idx].pixelFormat = ty.hasPrefix("uint") ? .rgba32Uint : ty.hasPrefix("int") ? .rgba32Sint : .rgba16Float
        }
        d.depthAttachmentPixelFormat = .depth32Float
        let t2 = now()
        _ = try dev.makeRenderPipelineState(descriptor: d, options: [], reflection: nil)
        r.pipe = ms(t2, now())
    } catch { r.err = String("\(error)".prefix(300)) }
    return r
}

let lock = NSLock()
var total = Result(), failed = 0
let t0 = now()
for _ in 0..<reps {
    let q = OperationQueue(); q.maxConcurrentOperationCount = jobs
    for p in args {
        q.addOperation {
            let r = one(p)
            lock.lock()
            if let e = r.err { failed += 1; if !quiet { print("FAIL \(p): \(e)") } }
            else {
                total.lib += r.lib; total.pipe += r.pipe; total.bytes += r.bytes
                if !quiet { print(String(format: "%@ bytes=%d lib=%.1f pipe=%.1f", (p as NSString).lastPathComponent, r.bytes, r.lib, r.pipe)) }
            }
            lock.unlock()
        }
    }
    q.waitUntilAllOperationsAreFinished()
}
let wall = ms(t0, now())
let n = Double(args.count * reps - failed)
print(String(format: "TOTAL files=%d reps=%d jobs=%d failed=%d wall=%.0f ms  sum(lib)=%.0f sum(pipe)=%.0f  mean lib=%.1f pipe=%.1f  wall/shader=%.1f ms",
             args.count, reps, jobs, failed, wall, total.lib, total.pipe, total.lib / n, total.pipe / n, wall / n))
