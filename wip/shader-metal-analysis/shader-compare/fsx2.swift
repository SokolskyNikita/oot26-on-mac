// fsx2: fsx with texture configurations.
//   fsx2 DIR [--reps N] [--data a,b] [--cfg c1,c2] [--fixss 0|1] name:math[:draws[:blend]] ...   (timing, interleaved)
//   fsx2 DIR --probe [--data ..] [--cfg ..] probe0 probe1 ...                                     (per-sample coordinate stats)
// cfgs: tinyshared (original fsx: one tiny texture per kind, shared by all slots), tiny (distinct tiny textures per slot),
//       mip (2048^2 rgba8, full mips, trilinear), nomip (2048^2 rgba8, 1 level, bilinear), aniso (mip + 8x anisotropy),
//       bc7 (2048^2 BC7 mode-6 random blocks, full mips, trilinear), astc (2048^2 ASTC 4x4 random blocks, full mips, trilinear).
// 2D arrays get 4 layers. All non-tinyshared textures are private storage, uploaded by blit, random content per level/layer.
import Metal
import Foundation
struct Buf: Decodable { let name: String; let id: Int; let kind: String; let elem: Int; let count: Int }
struct Slot: Decodable { let kind: String; let count: Int; let id: Int }
struct Meta: Decodable { let buffers: [Buf]; let textures: [Slot]; let samplers: [Slot]; let ncolor: Int; let max_id: Int }
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let W = 1920, H = 1080, SSBO = 1 << 22
struct RNG { var s: UInt64; mutating func next() -> UInt32 { s = s &* 6364136223846793005 &+ 1442695040888963407; return UInt32(truncatingIfNeeded: s >> 33) } }
setvbuf(stdout, nil, _IOLBF, 0)
var argv = Array(CommandLine.arguments.dropFirst()); let dir = argv.removeFirst()
func opt(_ k: String, _ def: String) -> String { if let i = argv.firstIndex(of: k) { let v = argv[i + 1]; argv.removeSubrange(i...(i + 1)); return v }; return def }
let probeMode = argv.contains("--probe"); argv.removeAll { $0 == "--probe" }
let reps = Int(opt("--reps", "3"))!, fixss = opt("--fixss", "1") == "1"
let dataNames = opt("--data", "floats,signed").split(separator: ",").map(String.init)
let cfgNames = opt("--cfg", "tinyshared,tiny,mip,nomip,aniso,bc7,astc").split(separator: ",").map(String.init)
let meta = try! JSONDecoder().decode(Meta.self, from: Data(contentsOf: URL(fileURLWithPath: dir + "/meta.json")))

// ---------- textures
var rng = RNG(s: 4242)
func tinyShared(_ kind: String) -> MTLTexture {   // identical to fsx
    let d = MTLTextureDescriptor(); d.pixelFormat = .rgba8Unorm; d.usage = [.shaderRead]; d.storageMode = .shared
    switch kind { case "texture3d": d.textureType = .type3D; d.width = 32; d.height = 32; d.depth = 32
    case "texturecube": d.textureType = .typeCube; d.width = 64; d.height = 64
    case "texture2d_array": d.textureType = .type2DArray; d.width = 128; d.height = 128; d.arrayLength = 4
    default: d.textureType = .type2D; d.width = 256; d.height = 256 }
    let t = dev.makeTexture(descriptor: d)!; var px = (0..<(d.width * d.height)).map { _ in rng.next() }
    for s in 0..<(kind == "texturecube" ? 6 : (kind == "texture2d_array" ? 4 : 1)) { for z in 0..<d.depth { px.withUnsafeMutableBytes { t.replace(region: MTLRegion(origin: MTLOrigin(x: 0, y: 0, z: z), size: MTLSize(width: d.width, height: d.height, depth: 1)), mipmapLevel: 0, slice: s, withBytes: $0.baseAddress!, bytesPerRow: d.width * 4, bytesPerImage: d.width * d.height * 4) } } }
    return t
}
var xs: UInt64 = 0x9E3779B97F4A7C15
func fillRandom(_ p: UnsafeMutableRawPointer, _ n: Int, bc7: Bool) {
    let w = p.bindMemory(to: UInt64.self, capacity: n / 8)
    for i in 0..<(n / 8) { xs ^= xs << 13; xs ^= xs >> 7; xs ^= xs << 17; w[i] = xs }
    if bc7 { let b = p.bindMemory(to: UInt8.self, capacity: n); for i in stride(from: 0, to: n, by: 16) { b[i] = (b[i] & 0x80) | 0x40 } }  // mode 6
}
func makeTex(kind: String, size: Int, layers: Int, mips: Bool, fmt: MTLPixelFormat) -> MTLTexture {
    let d = MTLTextureDescriptor(); d.pixelFormat = fmt; d.usage = [.shaderRead]; d.storageMode = .private
    d.textureType = kind == "texture2d_array" ? .type2DArray : .type2D; d.width = size; d.height = size
    if kind == "texture2d_array" { d.arrayLength = layers }
    let levels = mips ? Int(log2(Double(size))) + 1 : 1; d.mipmapLevelCount = levels
    let t = dev.makeTexture(descriptor: d)!
    let comp = fmt != .rgba8Unorm
    let cb = q.makeCommandBuffer()!, bl = cb.makeBlitCommandEncoder()!
    var staging = [MTLBuffer]()
    for s in 0..<(kind == "texture2d_array" ? layers : 1) { for l in 0..<levels {
        let w = max(1, size >> l)
        let bpr = comp ? max(1, (w + 3) / 4) * 16 : w * 4, rows = comp ? max(1, (w + 3) / 4) : w
        let n = max(16, bpr * rows), sb = dev.makeBuffer(length: (n + 15) & ~15, options: .storageModeShared)!
        fillRandom(sb.contents(), sb.length, bc7: fmt == .bc7_rgbaUnorm); staging.append(sb)
        bl.copy(from: sb, sourceOffset: 0, sourceBytesPerRow: bpr, sourceBytesPerImage: bpr * rows, sourceSize: MTLSize(width: w, height: w, depth: 1), to: t, destinationSlice: s, destinationLevel: l, destinationOrigin: MTLOrigin(x: 0, y: 0, z: 0))
    } }
    bl.endEncoding(); cb.commit(); cb.waitUntilCompleted()
    if let e = cb.error { print("upload error \(e)") }
    return t
}
func sampler(mip: Bool, aniso: Int) -> MTLSamplerState {
    let sd = MTLSamplerDescriptor(); sd.supportArgumentBuffers = true; sd.minFilter = .linear; sd.magFilter = .linear
    sd.sAddressMode = .repeat; sd.tAddressMode = .repeat; sd.rAddressMode = .repeat
    if mip { sd.mipFilter = .linear }; sd.maxAnisotropy = aniso
    return dev.makeSamplerState(descriptor: sd)!
}
struct Cfg { let name: String; let tex: [MTLTexture]; let samp: MTLSamplerState }   // tex[i] for meta.textures[i]
var cfgs = [Cfg]()
var bigMip: [MTLTexture]? = nil
for c in cfgNames {
    let t0 = Date()
    switch c {
    case "tinyshared": let m = ["texture2d": tinyShared("texture2d"), "texture2d_array": tinyShared("texture2d_array")]
        cfgs.append(Cfg(name: c, tex: meta.textures.map { m[$0.kind]! }, samp: sampler(mip: false, aniso: 1)))
    case "tiny": cfgs.append(Cfg(name: c, tex: meta.textures.map { $0.kind == "texture2d_array" ? makeTex(kind: $0.kind, size: 128, layers: 4, mips: false, fmt: .rgba8Unorm) : makeTex(kind: $0.kind, size: 256, layers: 1, mips: false, fmt: .rgba8Unorm) }, samp: sampler(mip: false, aniso: 1)))
    case "mip", "aniso":
        if bigMip == nil { bigMip = meta.textures.map { makeTex(kind: $0.kind, size: 2048, layers: 4, mips: true, fmt: .rgba8Unorm) } }
        cfgs.append(Cfg(name: c, tex: bigMip!, samp: sampler(mip: true, aniso: c == "aniso" ? 8 : 1)))
    case "nomip": cfgs.append(Cfg(name: c, tex: meta.textures.map { makeTex(kind: $0.kind, size: 2048, layers: 4, mips: false, fmt: .rgba8Unorm) }, samp: sampler(mip: false, aniso: 1)))
    case "bc7": guard dev.supportsBCTextureCompression else { print("no BC support"); continue }
        cfgs.append(Cfg(name: c, tex: meta.textures.map { makeTex(kind: $0.kind, size: 2048, layers: 4, mips: true, fmt: .bc7_rgbaUnorm) }, samp: sampler(mip: true, aniso: 1)))
    case "astc": guard dev.supportsFamily(.apple2) else { print("no ASTC support"); continue }
        cfgs.append(Cfg(name: c, tex: meta.textures.map { makeTex(kind: $0.kind, size: 2048, layers: 4, mips: true, fmt: .astc_4x4_ldr) }, samp: sampler(mip: true, aniso: 1)))
    default: print("unknown cfg \(c)")
    }
    print(String(format: "cfg %@ ready in %.1f s", c as NSString, Date().timeIntervalSince(t0)))
}
let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: W, height: H, mipmapped: false); td.usage = [.renderTarget]; td.storageMode = .shared
let target = dev.makeTexture(descriptor: td)!

// ---------- shaders
func compile(_ path: String, fast: Bool) -> MTLFunction? {
    guard let s = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
    let o = MTLCompileOptions(); o.languageVersion = .version3_2; o.mathMode = fast ? .fast : .safe; o.mathFloatingPointFunctions = fast ? .fast : .precise
    do { return try dev.makeLibrary(source: s, options: o).makeFunction(name: "main0") } catch { print("compile error \(path): \(error)".prefix(600)); return nil }
}
let vs = compile(dir + "/vs.metal", fast: false)!
struct V { let label: String; let pso: MTLRenderPipelineState; let draws: Int }
var vars = [V]()
for a in argv {
    var p = a.split(separator: ":").map(String.init); if p.count == 1 { p.append("safe") }
    let fast = p[1] == "fast"; let draws = p.count > 2 ? Int(p[2])! : 1; let blend = p.count > 3 && p[3] == "blend"
    guard let fs = compile(dir + "/v_\(p[0]).metal", fast: fast) else { continue }
    let d = MTLRenderPipelineDescriptor(); d.vertexFunction = vs; d.fragmentFunction = fs; d.colorAttachments[0].pixelFormat = .rgba32Float
    if blend { let c = d.colorAttachments[0]!; c.isBlendingEnabled = true; c.sourceRGBBlendFactor = .one; c.destinationRGBBlendFactor = .one; c.sourceAlphaBlendFactor = .one; c.destinationAlphaBlendFactor = .one }
    vars.append(V(label: a, pso: try! dev.makeRenderPipelineState(descriptor: d), draws: draws))
}

// ---------- data sets (same generator as fsx)
let modes = ["zeros", "mixed", "hibit", "floats", "floats+hibit", "floats+ints", "signed", "signed+hibit"]
func makeBufs(_ mode: Int) -> [MTLBuffer] {
    var r = RNG(s: 99)
    return meta.buffers.map { b in let n = (b.kind == "constant" ? b.count * b.elem : SSBO) / 4
        var d: [UInt32] = (0..<n).map { _ in if mode == 0 { return 0 }; let x = r.next()
            if mode == 3 { return (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 4 { return x % 4 == 3 ? 0x8000_0000 | ((x >> 4) & 0xFFFFF) : (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 6 || (mode == 7 && x % 4 != 3) { return ((Float((x >> 8) & 0xFFFF) / 65535.0 - 0.5) * 3.5).bitPattern }
            if mode == 7 { return 0x8000_0000 | ((x >> 4) & 0xFFFFF) }
            if mode == 5 { return x % 4 == 3 ? (x >> 4) & 7 : (0.25 + 1.5 * Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
            if mode == 2 && x % 3 == 2 { return 0x8000_0000 | ((x >> 4) & 0xFFFFF) }
            return x & 1 == 0 ? (x >> 1) & 3 : (Float((x >> 8) & 0xFFFF) / 65535.0).bitPattern }
        if fixss && b.name == "c3" { d[74] = (1.0 / Float(W)).bitPattern; d[75] = (1.0 / Float(H)).bitPattern }  // screen-space UV scale for fs_tex2_58
        return d.withUnsafeBytes { dev.makeBuffer(bytes: $0.baseAddress!, length: $0.count, options: .storageModeShared)! } }
}
struct Bind { let data: String; let cfg: Cfg; let arg: MTLBuffer; let bufs: [MTLBuffer] }
var binds = [Bind]()
for dn in dataNames {
    guard let mi = modes.firstIndex(of: dn) else { print("unknown data \(dn)"); continue }
    let bufs = makeBufs(mi)
    for c in cfgs {
        let arg = dev.makeBuffer(length: (meta.max_id + 1) * 8, options: .storageModeShared)!; memset(arg.contents(), 0, arg.length)
        let ap = arg.contents().bindMemory(to: UInt64.self, capacity: meta.max_id + 1)
        for (i, b) in meta.buffers.enumerated() { ap[b.id] = bufs[i].gpuAddress }
        for (i, t) in meta.textures.enumerated() { for k in 0..<t.count { arg.contents().advanced(by: (t.id + k) * 8).storeBytes(of: c.tex[i].gpuResourceID, as: MTLResourceID.self) } }
        for s in meta.samplers { for k in 0..<s.count { arg.contents().advanced(by: (s.id + k) * 8).storeBytes(of: c.samp.gpuResourceID, as: MTLResourceID.self) } }
        binds.append(Bind(data: dn, cfg: c, arg: arg, bufs: bufs))
    }
}
func run(_ v: V, _ b: Bind, _ n: Int, blendDraws: Int? = nil) -> [Double] {
    var t = [Double]()
    for _ in 0..<n {
        let pass = MTLRenderPassDescriptor(); pass.colorAttachments[0].texture = target; pass.colorAttachments[0].loadAction = .clear; pass.colorAttachments[0].storeAction = .store
        let cb = q.makeCommandBuffer()!, enc = cb.makeRenderCommandEncoder(descriptor: pass)!; enc.setRenderPipelineState(v.pso); enc.setFragmentBuffer(b.arg, offset: 0, index: 0)
        enc.useResources(b.bufs, usage: [.read], stages: .fragment); enc.useResources(b.cfg.tex, usage: [.read], stages: .fragment)
        for _ in 0..<(blendDraws ?? v.draws) { enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3) }
        enc.endEncoding(); cb.commit(); cb.waitUntilCompleted(); t.append((cb.gpuEndTime - cb.gpuStartTime) * 1000)
        if let e = cb.error { print("gpu error \(e)") }
    }
    return t
}
func readback() -> [Float] { var px = [Float](repeating: 0, count: W * H * 4); px.withUnsafeMutableBytes { target.getBytes($0.baseAddress!, bytesPerRow: W * 16, from: MTLRegionMake2D(0, 0, W, H), mipmapLevel: 0) }; return px }

if probeMode {
    for b in binds { for v in vars {
        _ = run(v, b, 1, blendDraws: 1); let px = readback()
        var ex = 0, fin = 0; var xs = [Float](), ys = [Float](), fp = [Float]()
        for i in stride(from: 0, to: px.count, by: 4) where px[i + 3] > 0.5 { ex += 1
            if px[i].isFinite && px[i + 1].isFinite && px[i + 2].isFinite { fin += 1; if i % 64 == 0 { xs.append(px[i]); ys.append(px[i + 1]); fp.append(px[i + 2]) } } }
        func pct(_ a: [Float], _ p: Double) -> Float { a.isEmpty ? .nan : a.sorted()[min(a.count - 1, Int(Double(a.count) * p))] }
        print(String(format: "%@ %@ %-8@ ran %5.1f%% finite %5.1f%% | x p5..p95 %10.4g .. %10.4g | y %10.4g .. %10.4g | footprint texels/px @2048 p10 %8.3g p50 %8.3g p90 %8.3g",
            b.data as NSString, b.cfg.name as NSString, v.label as NSString, 100 * Double(ex) / Double(W * H), ex == 0 ? 0 : 100 * Double(fin) / Double(ex),
            pct(xs, 0.05), pct(xs, 0.95), pct(ys, 0.05), pct(ys, 0.95), pct(fp, 0.1), pct(fp, 0.5), pct(fp, 0.9)))
    } }
    exit(0)
}
// sanity: output mean per (bind, variant), once
for b in binds { for v in vars {
    _ = run(v, b, 1); let px = readback(); var m = [Double](repeating: 0, count: 4); var bad = 0
    for i in stride(from: 0, to: px.count, by: 4) { for c in 0..<4 { if px[i + c].isFinite { m[c] += Double(px[i + c]) } else { bad += 1 } } }
    print(String(format: "sanity %@ %@ %@ mean rgba %.4f %.4f %.4f %.4f nan/inf %d", b.data as NSString, b.cfg.name as NSString, v.label as NSString, m[0] / Double(W * H), m[1] / Double(W * H), m[2] / Double(W * H), m[3] / Double(W * H), bad))
} }
// timing: every rep visits every (bind, variant) once; order rotates per rep
var jobs = [(Int, Int)](); for bi in binds.indices { for vi in vars.indices { jobs.append((bi, vi)) } }
for r in 0..<reps {
    var order = jobs; var g = RNG(s: UInt64(r + 1) * 7919); for i in stride(from: order.count - 1, to: 0, by: -1) { order.swapAt(i, Int(g.next()) % (i + 1)) }
    for (bi, vi) in order {
        let t = Array(run(vars[vi], binds[bi], 17).dropFirst(2)).sorted()
        print(String(format: "T rep %d data %@ cfg %@ var %@ min %.4f med %.4f", r, binds[bi].data as NSString, binds[bi].cfg.name as NSString, vars[vi].label as NSString, t[0], t[t.count / 2]))
    }
}
