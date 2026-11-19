// mipfix: one cached fragment shader whose samples sit behind a per-pixel condition. Mip textures hold their level number,
// so the output shows which mip each pixel got. Variants: asgen (as MoltenVK emits), ref (samples hoisted out of the branch),
// fix (gradients taken before the branch, samples still conditional).
import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let W = 1920, H = 1080
func tex(_ size: Int, mips: Bool, fill: (Int, Int, Int, Int) -> Float) -> MTLTexture {
    let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .r32Float, width: size, height: size, mipmapped: mips)
    let t = dev.makeTexture(descriptor: d)!
    for l in 0..<t.mipmapLevelCount { let s = max(1, size >> l); var px = [Float](repeating: 0, count: s * s)
        for y in 0..<s { for x in 0..<s { px[y * s + x] = fill(l, x, y, s) } }
        t.replace(region: MTLRegionMake2D(0, 0, s, s), mipmapLevel: l, withBytes: px, bytesPerRow: s * 4) }
    return t }
// mask: round blobs of 1 on 0, so the condition flips along curved edges
let mask = tex(256, mips: false) { _, x, y, s in let cx = Float(x % 64) - 32, cy = Float(y % 64) - 32; return cx * cx + cy * cy < 400 ? 1 : 0 }
let level = tex(1024, mips: true) { l, _, _, _ in Float(l) }
let sd = MTLSamplerDescriptor(); sd.minFilter = .linear; sd.magFilter = .linear; sd.mipFilter = .linear; sd.sAddressMode = .repeat; sd.tAddressMode = .repeat
let smp = dev.makeSamplerState(descriptor: sd)!
let zero = dev.makeBuffer(length: 16384 * 4 + 4096, options: .storageModeShared)!
let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: W, height: H, mipmapped: false); td.usage = [.renderTarget]; td.storageMode = .shared
func run(_ name: String, draws: Int, blend: Bool) -> ([Float], Double) {
    let o = MTLCompileOptions(); o.languageVersion = .version3_2; o.mathMode = .safe; o.mathFloatingPointFunctions = .precise
    let lib = try! dev.makeLibrary(source: try! String(contentsOfFile: "v_\(name).metal", encoding: .utf8), options: o)
    let pd = MTLRenderPipelineDescriptor(); pd.vertexFunction = lib.makeFunction(name: "vmain"); pd.fragmentFunction = lib.makeFunction(name: "main0")
    pd.colorAttachments[0].pixelFormat = .rgba32Float
    if blend { let a = pd.colorAttachments[0]!; a.isBlendingEnabled = true; a.sourceRGBBlendFactor = .one; a.destinationRGBBlendFactor = .one; a.sourceAlphaBlendFactor = .one; a.destinationAlphaBlendFactor = .one }
    let ps = try! dev.makeRenderPipelineState(descriptor: pd); let target = dev.makeTexture(descriptor: td)!
    var best = Double.infinity
    for _ in 0..<(draws > 1 ? 25 : 1) {
        let rp = MTLRenderPassDescriptor(); rp.colorAttachments[0].texture = target; rp.colorAttachments[0].loadAction = .clear; rp.colorAttachments[0].storeAction = .store
        let cb = q.makeCommandBuffer()!, e = cb.makeRenderCommandEncoder(descriptor: rp)!; e.setRenderPipelineState(ps)
        for i in 1...4 { e.setFragmentBuffer(zero, offset: 0, index: i) }
        e.setFragmentTextures([level, level, level, mask], range: 0..<4)   // 20, 28, 30 = level textures; 38 = mask
        e.setFragmentSamplerStates([smp, smp, smp, smp], range: 0..<4)
        for _ in 0..<draws { e.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3) }
        e.endEncoding(); cb.commit(); cb.waitUntilCompleted(); best = min(best, (cb.gpuEndTime - cb.gpuStartTime) * 1000) }
    var px = [Float](repeating: 0, count: W * H * 4)
    target.getBytes(&px, bytesPerRow: W * 16, from: MTLRegionMake2D(0, 0, W, H), mipmapLevel: 0)
    return (px, best) }
let names = ["ref", "asgen", "fix"]; var img = [String: [Float]]()
for n in names { img[n] = run(n, draws: 1, blend: false).0 }
let R = img["ref"]!
// channel x: level seen by fs_tex2_30 where the mask is 0; channel y: level seen by fs_tex2_20 where the mask is 1 (10000 elsewhere)
func masked(_ x: Int, _ y: Int) -> Bool { R[(y * W + x) * 4 + 1] != 10000 }
var edge = [Bool](repeating: false, count: W * H); var nEdge = 0
for y in stride(from: 0, to: H, by: 2) { for x in stride(from: 0, to: W, by: 2) {
    let m = [masked(x, y), masked(x + 1, y), masked(x, y + 1), masked(x + 1, y + 1)]
    if Set(m).count > 1 { for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] { edge[(y + dy) * W + x + dx] = true }; nEdge += 4 } } }
var refLevels = [Float](); for i in stride(from: 0, to: W * H, by: 997) { refLevels.append(masked(i % W, i / W) ? R[i * 4 + 1] : R[i * 4]) }
print("device \(dev.name); reference mip level: min \(refLevels.min()!) max \(refLevels.max()!); pixels in quads where the condition differs: \(nEdge) of \(W * H) (\(String(format: "%.2f", 100 * Double(nEdge) / Double(W * H)))%)")
for n in ["asgen", "fix"] { let A = img[n]!
    var dEdge = 0, dRest = 0, bit = 0; var worst: Float = 0, sum: Double = 0
    for i in 0..<(W * H) { var differs = false; var d: Float = 0
        for c in 0..<2 { let a = A[i * 4 + c], r = R[i * 4 + c]; if a.bitPattern != r.bitPattern { bit += 1 }; if a != r { differs = true; d = max(d, abs(a - r)) } }
        if differs && d > 0.01 { if edge[i] { dEdge += 1 } else { dRest += 1 }; worst = max(worst, d); sum += Double(d) } }
    print(String(format: "%-5@ vs ref: pixels off by >0.01 mip level: %d in edge quads (%.1f%% of them), %d elsewhere; worst %.2f levels, mean of those %.2f; channel values not bit-identical: %d",
        n as NSString, dEdge, nEdge > 0 ? 100 * Double(dEdge) / Double(nEdge) : 0, dRest, worst, (dEdge + dRest) > 0 ? sum / Double(dEdge + dRest) : 0, bit)) }
for rep in 0..<3 { var s = "timing rep \(rep), 8 blended 1080p passes, min of 25 (ms):"
    for n in names + names.reversed() { s += String(format: "  %@ %.3f", n as NSString, run(n, draws: 8, blend: true).1) }; print(s) }
