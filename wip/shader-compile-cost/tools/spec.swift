// spec: cost of pipeline variants that differ only in blend state or colour format, old path vs Metal 4 specialization.
// Usage: MTL_SHADER_CACHE_SIZE=0 spec [-reps R] [-mode old|mtl4|both] FS.metal
// Variants (applied to every float colour attachment; integer attachments keep rgba32Uint/Sint, blending off):
//   V1 rgba16Float blend off   V2 rgba16Float blend on   V3 bgra8Unorm blend off   V4 bgra8Unorm blend on
// old : device.makeLibrary once, then makeRenderPipelineState for V1, V2, V3, V4 in turn (each timed)
// m4f : MTL4Compiler, library once, full (specialized) pipeline for V1..V4 (each timed)
// m4u : MTL4Compiler, library once, one unspecialized pipeline (format, blend, write mask unspecialized), then
//       newRenderPipelineStateBySpecialization to V1..V4 (each timed)
// Each rep uses a fresh entry-point name so nothing is reused between reps.
import Metal
import Foundation

func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
func ms(_ a: UInt64, _ b: UInt64) -> Double { Double(b - a) / 1e6 }

var args = Array(CommandLine.arguments.dropFirst())
var reps = 1, mode = "both"
while let a = args.first, a.hasPrefix("-") {
    args.removeFirst()
    switch a {
    case "-reps": reps = Int(args.removeFirst())!
    case "-mode": mode = args.removeFirst()
    default: fatalError("bad flag \(a)")
    }
}
let path = args[0]
let dev = MTLCreateSystemDefaultDevice()!
func options() -> MTLCompileOptions {
    let o = MTLCompileOptions(); o.languageVersion = .version4_0
    o.mathMode = .safe; o.mathFloatingPointFunctions = .precise; return o
}
let compiler = try! dev.makeCompiler(descriptor: MTL4CompilerDescriptor())
_ = try! dev.makeLibrary(source: "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }", options: nil)
do { let ld = MTL4LibraryDescriptor(); ld.source = "fragment float4 w\(UInt32.random(in: 0..<UInt32.max))() { return float4(1.0); }"; _ = try! compiler.makeLibrary(descriptor: ld) }

let src0 = try! String(contentsOfFile: path, encoding: .utf8)
let inRe = try! NSRegularExpression(pattern: #"struct main0_in\s*\{([^}]*)\}"#)
let colRe = try! NSRegularExpression(pattern: #"(\w+)\s+\w+\s*\[\[color\((\d+)\)"#)
var fields = ""
if let m = inRe.firstMatch(in: src0, range: NSRange(src0.startIndex..., in: src0)) { fields = String(src0[Range(m.range(at: 1), in: src0)!]) }
var cols: [(Int, MTLPixelFormat?)] = []   // nil = float attachment that varies
for m in colRe.matches(in: src0, range: NSRange(src0.startIndex..., in: src0)) {
    let ty = String(src0[Range(m.range(at: 1), in: src0)!]); let idx = Int(src0[Range(m.range(at: 2), in: src0)!])!
    cols.append((idx, ty.hasPrefix("uint") ? .rgba32Uint : ty.hasPrefix("int") ? .rgba32Sint : nil))
}
struct Variant { var fmt: MTLPixelFormat; var blend: Bool; var name: String }
let variants = [Variant(fmt: .rgba16Float, blend: false, name: "V1 rgba16F/off"), Variant(fmt: .rgba16Float, blend: true, name: "V2 rgba16F/on"),
                Variant(fmt: .bgra8Unorm, blend: false, name: "V3 bgra8/off"), Variant(fmt: .bgra8Unorm, blend: true, name: "V4 bgra8/on")]

func sources() -> (String, String, String) {
    let n = "m\(UInt32.random(in: 0..<UInt32.max))x"
    let vsrc = "#include <metal_stdlib>\nusing namespace metal;\nstruct VO { float4 pos [[position]]; \(fields) };\n"
        + "vertex VO \(n)v(uint vid [[vertex_id]]) { VO o = {}; o.pos = float4(float(vid)); return o; }\n"
    return (n, src0.replacingOccurrences(of: "main0", with: n), vsrc)
}

func oldRun() -> (Double, [Double], String?) {
    let (n, src, vsrc) = sources()
    do {
        let vl = try dev.makeLibrary(source: vsrc, options: options())
        let t0 = now(); let fl = try dev.makeLibrary(source: src, options: options()); let lib = ms(t0, now())
        var t: [Double] = []
        for v in variants {
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = vl.makeFunction(name: n + "v")!; d.fragmentFunction = fl.makeFunction(name: n)!
            for (i, f) in cols {
                d.colorAttachments[i].pixelFormat = f ?? v.fmt
                if f == nil && v.blend {
                    let c = d.colorAttachments[i]!; c.isBlendingEnabled = true
                    c.sourceRGBBlendFactor = .sourceAlpha; c.destinationRGBBlendFactor = .oneMinusSourceAlpha
                    c.sourceAlphaBlendFactor = .one; c.destinationAlphaBlendFactor = .oneMinusSourceAlpha
                }
            }
            d.depthAttachmentPixelFormat = .depth32Float
            let a = now(); _ = try dev.makeRenderPipelineState(descriptor: d, options: [], reflection: nil); t.append(ms(a, now()))
        }
        return (lib, t, nil)
    } catch { return (0, [], "\(error)") }
}

func m4desc(_ vl: MTLLibrary, _ fl: MTLLibrary, _ n: String, _ v: Variant?) -> MTL4RenderPipelineDescriptor {
    let d = MTL4RenderPipelineDescriptor()
    let vf = MTL4LibraryFunctionDescriptor(); vf.library = vl; vf.name = n + "v"
    let ff = MTL4LibraryFunctionDescriptor(); ff.library = fl; ff.name = n
    d.vertexFunctionDescriptor = vf; d.fragmentFunctionDescriptor = ff
    for (i, f) in cols {
        let c = d.colorAttachments[i]!
        if let f = f { c.pixelFormat = f; c.blendingState = .disabled; continue }
        if let v = v {
            c.pixelFormat = v.fmt; c.writeMask = .all
            if v.blend {
                c.blendingState = .enabled
                c.sourceRGBBlendFactor = .sourceAlpha; c.destinationRGBBlendFactor = .oneMinusSourceAlpha; c.rgbBlendOperation = .add
                c.sourceAlphaBlendFactor = .one; c.destinationAlphaBlendFactor = .oneMinusSourceAlpha; c.alphaBlendOperation = .add
            } else { c.blendingState = .disabled }
        } else {
            c.pixelFormat = .unspecialized; c.blendingState = .unspecialized; c.writeMask = .unspecialized
            c.sourceRGBBlendFactor = .unspecialized; c.destinationRGBBlendFactor = .unspecialized; c.rgbBlendOperation = .unspecialized
            c.sourceAlphaBlendFactor = .unspecialized; c.destinationAlphaBlendFactor = .unspecialized; c.alphaBlendOperation = .unspecialized
        }
    }
    return d
}

func m4Run(_ unspec: Bool) -> (Double, Double, [Double], String?) {
    let (n, src, vsrc) = sources()
    do {
        let vd = MTL4LibraryDescriptor(); vd.source = vsrc; vd.options = options()
        let vl = try compiler.makeLibrary(descriptor: vd)
        let fd = MTL4LibraryDescriptor(); fd.source = src; fd.options = options()
        let t0 = now(); let fl = try compiler.makeLibrary(descriptor: fd); let lib = ms(t0, now())
        var t: [Double] = [], u = 0.0
        if unspec {
            let a = now(); let up = try compiler.makeRenderPipelineState(descriptor: m4desc(vl, fl, n, nil)); u = ms(a, now())
            for v in variants {
                let b = now(); let sp = try compiler.makeRenderPipelineStateBySpecialization(descriptor: m4desc(vl, fl, n, v), pipeline: up); t.append(ms(b, now()))
                _ = sp.gpuResourceID
            }
        } else {
            for v in variants {
                let b = now(); let p = try compiler.makeRenderPipelineState(descriptor: m4desc(vl, fl, n, v)); t.append(ms(b, now())); _ = p.gpuResourceID
            }
        }
        return (lib, u, t, nil)
    } catch { return (0, 0, [], "\(error)") }
}

func f(_ a: [Double]) -> String { a.map { String(format: "%.1f", $0) }.joined(separator: " ") }
for r in 0..<reps {
    if mode == "old" || mode == "both" {
        let (lib, t, e) = oldRun()
        if let e = e { print("old FAIL \(e.prefix(300))") } else { print("rep=\(r) old lib=\(String(format: "%.1f", lib)) unspec=- V1..V4= \(f(t))") }
    }
    if mode == "mtl4" || mode == "both" {
        let (lib, _, t, e) = m4Run(false)
        if let e = e { print("m4f FAIL \(e.prefix(300))") } else { print("rep=\(r) m4f lib=\(String(format: "%.1f", lib)) unspec=- V1..V4= \(f(t))") }
        let (lib2, u, t2, e2) = m4Run(true)
        if let e = e2 { print("m4u FAIL \(e.prefix(300))") } else { print("rep=\(r) m4u lib=\(String(format: "%.1f", lib2)) unspec=\(String(format: "%.1f", u)) V1..V4= \(f(t2))") }
    }
}
