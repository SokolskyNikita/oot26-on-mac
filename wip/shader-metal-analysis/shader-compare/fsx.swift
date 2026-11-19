// fsx DIR name:math[:draws[:blend]] ... : time variants DIR/v_<name>.metal of one fragment shader full-screen and compare pixels with the first.
import Metal
import Foundation
struct Buf: Decodable { let name: String; let id: Int; let kind: String; let elem: Int; let count: Int }
struct Slot: Decodable { let kind: String; let count: Int; let id: Int }
struct Meta: Decodable { let buffers: [Buf]; let textures: [Slot]; let samplers: [Slot]; let ncolor: Int; let max_id: Int }
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let W = 1920, H = 1080, SSBO = 1 << 22
struct RNG { var s: UInt64; mutating func next() -> UInt32 { s = s &* 6364136223846793005 &+ 1442695040888963407; return UInt32(truncatingIfNeeded: s >> 33) } }
var rng = RNG(s: 4242)
func tex(_ kind: String) -> MTLTexture {
    let d = MTLTextureDescriptor(); d.pixelFormat = .rgba8Unorm; d.usage = [.shaderRead]; d.storageMode = .shared
    switch kind { case "texture3d": d.textureType = .type3D; d.width = 32; d.height = 32; d.depth = 32
    case "texturecube": d.textureType = .typeCube; d.width = 64; d.height = 64
    case "texture2d_array": d.textureType = .type2DArray; d.width = 128; d.height = 128; d.arrayLength = 4
    default: d.textureType = .type2D; d.width = 256; d.height = 256 }
    let t = dev.makeTexture(descriptor: d)!; var px = (0..<(d.width * d.height)).map { _ in rng.next() }
    for s in 0..<(kind == "texturecube" ? 6 : (kind == "texture2d_array" ? 4 : 1)) { for z in 0..<d.depth { px.withUnsafeMutableBytes { t.replace(region: MTLRegion(origin: MTLOrigin(x: 0, y: 0, z: z), size: MTLSize(width: d.width, height: d.height, depth: 1)), mipmapLevel: 0, slice: s, withBytes: $0.baseAddress!, bytesPerRow: d.width * 4, bytesPerImage: d.width * d.height * 4) } } }
    return t
}
let texes = ["texture2d": tex("texture2d"), "texture2d_array": tex("texture2d_array"), "texture3d": tex("texture3d"), "texturecube": tex("texturecube")]
let sd = MTLSamplerDescriptor(); sd.supportArgumentBuffers = true; sd.minFilter = .linear; sd.magFilter = .linear; sd.sAddressMode = .repeat; sd.tAddressMode = .repeat; sd.rAddressMode = .repeat
let samp = dev.makeSamplerState(descriptor: sd)!
let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: W, height: H, mipmapped: false); td.usage = [.renderTarget]; td.storageMode = .shared
let target = dev.makeTexture(descriptor: td)!
func compile(_ path: String, fast: Bool) -> MTLFunction? {
    guard let s = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
    let o = MTLCompileOptions(); o.languageVersion = .version3_2; o.mathMode = fast ? .fast : .safe; o.mathFloatingPointFunctions = fast ? .fast : .precise
    do { return try dev.makeLibrary(source: s, options: o).makeFunction(name: "main0") } catch { print("compile error \(path): \(error)".prefix(600)); return nil }
}
setvbuf(stdout, nil, _IOLBF, 0)
let args = Array(CommandLine.arguments.dropFirst()); let dir = args[0]
let meta = try! JSONDecoder().decode(Meta.self, from: Data(contentsOf: URL(fileURLWithPath: dir + "/meta.json")))
let vs = compile(dir + "/vs.metal", fast: false)!
struct V { let label: String; let pso: MTLRenderPipelineState; let draws: Int }
var vars = [V]()
for a in args.dropFirst() {
    let p = a.split(separator: ":").map(String.init); let fast = p[1] == "fast"; let draws = p.count > 2 ? Int(p[2])! : 1; let blend = p.count > 3 && p[3] == "blend"
    guard let fs = compile(dir + "/v_\(p[0]).metal", fast: fast) else { continue }
    let d = MTLRenderPipelineDescriptor(); d.vertexFunction = vs; d.fragmentFunction = fs; d.colorAttachments[0].pixelFormat = .rgba32Float
    if blend { let c = d.colorAttachments[0]!; c.isBlendingEnabled = true; c.sourceRGBBlendFactor = .one; c.destinationRGBBlendFactor = .one; c.sourceAlphaBlendFactor = .one; c.destinationAlphaBlendFactor = .one }
    vars.append(V(label: a, pso: try! dev.makeRenderPipelineState(descriptor: d), draws: draws))
}
let modes = ["zeros", "mixed", "hibit", "floats", "floats+hibit", "floats+ints", "signed", "signed+hibit"]
for (mode, mname) in modes.enumerated() {
    var r = RNG(s: 99)
    let bufs: [MTLBuffer] = meta.buffers.map { b in let n = (b.kind == "constant" ? b.count * b.elem : SSBO) / 4
        let d: [UInt32] = (0..<n).map { _ in if mode == 0 { return 0 }; let x = r.next()
            if mode == 3 { return (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 4 { return x % 4 == 3 ? 0x8000_0000 | ((x >> 4) & 0xFFFFF) : (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 6 || (mode == 7 && x % 4 != 3) { return ((Float((x >> 8) & 0xFFFF) / 65535.0 - 0.5) * 3.5).bitPattern }
            if mode == 7 { return 0x8000_0000 | ((x >> 4) & 0xFFFFF) }
            if mode == 5 { return x % 4 == 3 ? (x >> 4) & 7 : (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 2 && x % 3 == 2 { return 0x8000_0000 | ((x >> 4) & 0xFFFFF) }
            return x & 1 == 0 ? (x >> 1) & 3 : (Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
        return d.withUnsafeBytes { dev.makeBuffer(bytes: $0.baseAddress!, length: $0.count, options: .storageModeShared)! } }
    let arg = dev.makeBuffer(length: (meta.max_id + 1) * 8, options: .storageModeShared)!; memset(arg.contents(), 0, arg.length)
    let ap = arg.contents().bindMemory(to: UInt64.self, capacity: meta.max_id + 1)
    for (i, b) in meta.buffers.enumerated() { ap[b.id] = bufs[i].gpuAddress }
    for t in meta.textures { for k in 0..<t.count { arg.contents().advanced(by: (t.id + k) * 8).storeBytes(of: texes[t.kind]!.gpuResourceID, as: MTLResourceID.self) } }
    for s in meta.samplers { for k in 0..<s.count { arg.contents().advanced(by: (s.id + k) * 8).storeBytes(of: samp.gpuResourceID, as: MTLResourceID.self) } }
    var ref = [UInt32]()
    print("--- data: \(mname)")
    for v in vars {
        var t = [Double]()
        for _ in 0..<17 {
            let pass = MTLRenderPassDescriptor(); pass.colorAttachments[0].texture = target; pass.colorAttachments[0].loadAction = .clear; pass.colorAttachments[0].storeAction = .store
            let cb = q.makeCommandBuffer()!, enc = cb.makeRenderCommandEncoder(descriptor: pass)!; enc.setRenderPipelineState(v.pso); enc.setFragmentBuffer(arg, offset: 0, index: 0)
            for b in bufs { enc.useResource(b, usage: [.read], stages: .fragment) }; for x in texes.values { enc.useResource(x, usage: [.read], stages: .fragment) }
            for _ in 0..<v.draws { enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3) }
            enc.endEncoding(); cb.commit(); cb.waitUntilCompleted(); t.append((cb.gpuEndTime - cb.gpuStartTime) * 1000)
        }
        t = Array(t.dropFirst(2)).sorted()
        var px = [UInt32](repeating: 0, count: W * H * 4)
        px.withUnsafeMutableBytes { target.getBytes($0.baseAddress!, bytesPerRow: W * 16, from: MTLRegionMake2D(0, 0, W, H), mipmapLevel: 0) }
        var mean = [Double](repeating: 0, count: 4); var nan = 0
        func f(_ h: UInt32) -> Float { Float(bitPattern: h) }
        for i in stride(from: 0, to: px.count, by: 4) { for c in 0..<4 { let x = f(px[i + c]); if x.isNaN || x.isInfinite { nan += 1 } else { mean[c] += Double(x) } } }
        var cmp = "(reference)"
        if ref.isEmpty { ref = px } else {
            var diff = 0, big = 0; var maxd: Float = 0
            for i in stride(from: 0, to: px.count, by: 4) { var d = false; for c in 0..<4 where px[i + c] != ref[i + c] { d = true; let a = f(px[i + c]), b = f(ref[i + c]); if a.isFinite && b.isFinite { let e = abs(a - b) / max(1e-3, abs(b)); maxd = max(maxd, e); if e > 0.01 { big += 1 } } else { big += 1 } }; if d { diff += 1 } }
            cmp = String(format: "pixels differing %7d (%.3f%%), >1%% off: %d, max rel diff %.4f", diff, 100 * Double(diff) / Double(W * H), big, maxd)
        }
        print(String(format: "%-22@ median %6.2f ms  min %6.2f | mean rgba %.4f %.4f %.4f %.4f nan/inf %d | %@", v.label as NSString, t[t.count / 2], t[0], mean[0] / Double(W * H), mean[1] / Double(W * H), mean[2] / Double(W * H), mean[3] / Double(W * H), nan, cmp))
    }
}
