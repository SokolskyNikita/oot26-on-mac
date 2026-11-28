// cbench: cold compile timing of compute (kernel) MSL, same compile options as ../bench.swift.
// Usage: MTL_SHADER_CACHE_SIZE=0 cbench [-reps R] [-q] [-licm] [-archive PATH] CS.metal...
// Per file: makeLibrary(source:) (MSL -> AIR) and makeComputePipelineState(descriptor:) (AIR -> GPU code).
// Each compile gets a fresh entry-point name so nothing is reused.
//   -licm          driverCompilerOptions = ["agx_disable_licm": true] on the MTLComputePipelineDescriptor (KVC)
//   -archive PATH  only write a binary archive per file (PATH is the file for one input, a folder for several); no timing
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { Double(b - a) / 1e6 }

var args = Array(CommandLine.arguments.dropFirst())
var reps = 1, quiet = false, licm = false, archivePath: String? = nil
while let a = args.first, a.hasPrefix("-") {
    args.removeFirst()
    switch a {
    case "-reps": reps = Int(args.removeFirst())!
    case "-q": quiet = true
    case "-licm": licm = true
    case "-archive": archivePath = args.removeFirst()
    default: fatalError("bad flag \(a)")
    }
}
let dev = MTLCreateSystemDefaultDevice()!
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions()
    o.languageVersion = .version4_0
    o.mathMode = .safe; o.mathFloatingPointFunctions = .precise
    return o
}
_ = try! dev.makeLibrary(source: "kernel void w\(UInt32.random(in: 0..<UInt32.max))() {}", options: nil)

struct Result { var lib = 0.0, pipe = 0.0, err: String? = nil }
func one(_ path: String) -> Result {
    var r = Result()
    let src0 = try! String(contentsOfFile: path, encoding: .utf8)
    let n = "m\(UInt32.random(in: 0..<UInt32.max))x"
    let src = src0.replacingOccurrences(of: "main0", with: n)
    do {
        let t0 = now()
        let lib = try dev.makeLibrary(source: src, options: options())
        r.lib = ms(t0, now())
        let d = MTLComputePipelineDescriptor()
        d.computeFunction = lib.makeFunction(name: n)!
        if licm { d.setValue(["agx_disable_licm": true], forKey: "driverCompilerOptions") }
        if let ap0 = archivePath {
            let ap = args.count > 1 ? ap0 + "/" + (path as NSString).lastPathComponent + ".bin" : ap0
            let ar = try dev.makeBinaryArchive(descriptor: MTLBinaryArchiveDescriptor())
            try ar.addComputePipelineFunctions(descriptor: d)
            try? FileManager.default.removeItem(atPath: ap)
            try ar.serialize(to: URL(fileURLWithPath: ap))
            return r
        }
        let t2 = now()
        let ps = try dev.makeComputePipelineState(descriptor: d, options: [], reflection: nil)
        r.pipe = ms(t2, now())
        _ = ps.maxTotalThreadsPerThreadgroup
    } catch { r.err = String("\(error)".prefix(300)) }
    return r
}

var libs: [Double] = [], pipes: [Double] = [], failed = 0
for _ in 0..<reps {
    for p in args {
        let r = one(p)
        if let e = r.err { failed += 1; if !quiet { print("FAIL \(p): \(e)") }; continue }
        libs.append(r.lib); pipes.append(r.pipe)
        if !quiet { print(String(format: "%@ lib=%.1f pipe=%.1f", (p as NSString).lastPathComponent, r.lib, r.pipe)) }
    }
}
let n = Double(max(libs.count, 1))
print(String(format: "TOTAL files=%d reps=%d failed=%d licm_off=%d  mean lib=%.1f pipe=%.1f  min lib=%.1f pipe=%.1f",
             args.count, reps, failed, licm ? 1 : 0, libs.reduce(0, +) / n, pipes.reduce(0, +) / n, libs.min() ?? 0, pipes.min() ?? 0))
