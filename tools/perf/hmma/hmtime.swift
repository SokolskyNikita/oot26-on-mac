// hmtime time FILE.metal...   GPU time of each variant of the network-upscale kernel (the game's grid: 30 x 34
//                             groups of 128) and whether its 1920x1080 output equals the first file's, byte for byte.
// hmtime unit unit.metal      runs the original emulated HMMA and the replacements on the same random fragments
//                             (several value classes) and compares the results bit for bit.
// Inputs are made up: a random 1440x810 image and random small signed fp16 weights.
import Foundation
import Metal

let dev = MTLCreateSystemDefaultDevice()!
let q = dev.makeCommandQueue()!
struct RNG { var s: UInt64; mutating func next() -> UInt32 { s = s &* 6364136223846793005 &+ 1442695040888963407; return UInt32(truncatingIfNeeded: s >> 33) ^ UInt32(truncatingIfNeeded: s >> 11) } }
setvbuf(stdout, nil, _IOLBF, 0)

func lib(_ path: String) -> MTLLibrary? {
    let o = MTLCompileOptions()
    o.languageVersion = .version3_2
    o.mathMode = .safe
    o.mathFloatingPointFunctions = .precise
    do { return try dev.makeLibrary(source: try String(contentsOfFile: path, encoding: .utf8), options: o) }
    catch { print("\(path): compile failed: \(error)".prefix(1200)); return nil }
}

let mode = CommandLine.arguments[1]
if mode == "time" {
    var rng = RNG(s: 7)
    // "--real DIR": the game's own constant buffer, weights and input image from a frame dump (cbuf.bin, ssbo.bin,
    // in.raw as E5B9G9R9, expect.raw as the B10G11R11 image the game's pass wrote in that frame).
    var realDir: String? = nil
    if let i = CommandLine.arguments.firstIndex(of: "--real") { realDir = CommandLine.arguments[i + 1] }
    var cbBytes = [UInt8](repeating: 0, count: 65536)
    var wBytes = [UInt8](repeating: 0, count: 1 << 20)
    var px = [UInt32](repeating: 0, count: 1440 * 810)
    var expect: [UInt32]? = nil
    if let d = realDir {
        let c = [UInt8](try! Data(contentsOf: URL(fileURLWithPath: d + "/cbuf.bin"))); cbBytes.replaceSubrange(0..<c.count, with: c)
        let w = [UInt8](try! Data(contentsOf: URL(fileURLWithPath: d + "/ssbo.bin"))); wBytes.replaceSubrange(0..<w.count, with: w)
        (try! Data(contentsOf: URL(fileURLWithPath: d + "/in.raw"))).withUnsafeBytes { b in for i in 0..<px.count { px[i] = b.loadUnaligned(fromByteOffset: i * 4, as: UInt32.self) } }
        var e = [UInt32](repeating: 0, count: 1920 * 1080)
        (try! Data(contentsOf: URL(fileURLWithPath: d + "/expect.raw"))).withUnsafeBytes { b in for i in 0..<e.count { e[i] = b.loadUnaligned(fromByteOffset: i * 4, as: UInt32.self) } }
        expect = e
    } else {
        var cb = [Float](repeating: 0, count: 16384)
        cb[12] = 1.0 / 1440.0; cb[13] = 1.0 / 810.0
        cb.withUnsafeBytes { cbBytes.replaceSubrange(0..<65536, with: $0) }
        let big = CommandLine.arguments.contains("--big")
        for i in 0..<(1 << 19) {
            let r = rng.next()
            let h = big ? UInt16(0x3000 + Int(r % 0x0C00)) : UInt16((r & 0x8000) | (0x2800 + (r >> 16) % 0x0C00))
            wBytes[2 * i] = UInt8(h & 0xFF); wBytes[2 * i + 1] = UInt8(h >> 8)
        }
        for i in 0..<px.count { px[i] = rng.next() & 0x3DEF7BDE }
    }
    let cbuf = dev.makeBuffer(bytes: cbBytes, length: cbBytes.count, options: .storageModeShared)!
    let ssbo = dev.makeBuffer(bytes: wBytes, length: wBytes.count, options: .storageModeShared)!
    let ind = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: realDir != nil ? .rgb9e5Float : .rg11b10Float, width: 1440, height: 810, mipmapped: false)
    ind.usage = [.shaderRead]; ind.storageMode = .shared
    let inTex = dev.makeTexture(descriptor: ind)!
    px.withUnsafeMutableBytes { inTex.replace(region: MTLRegionMake2D(0, 0, 1440, 810), mipmapLevel: 0, withBytes: $0.baseAddress!, bytesPerRow: 1440 * 4) }
    let outd = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rg11b10Float, width: 1920, height: 1080, mipmapped: false)
    outd.usage = [.shaderWrite, .shaderRead]; outd.storageMode = .shared
    let sd = MTLSamplerDescriptor(); sd.minFilter = .linear; sd.magFilter = .linear; sd.sAddressMode = .clampToEdge; sd.tAddressMode = .clampToEdge
    let samp = dev.makeSamplerState(descriptor: sd)!
    var ref: [UInt32]? = nil
    for path in CommandLine.arguments[2...] where path.hasSuffix(".metal") {
        guard let l = lib(path), let p = try? dev.makeComputePipelineState(function: l.makeFunction(name: "main0")!) else { print("\(path): no pipeline"); continue }
        let outTex = dev.makeTexture(descriptor: outd)!
        var t = [Double]()
        for i in 0..<17 {
            let c = q.makeCommandBuffer()!
            let e = c.makeComputeCommandEncoder()!
            e.setComputePipelineState(p)
            e.setBuffer(cbuf, offset: 0, index: 1); e.setBuffer(ssbo, offset: 0, index: 2)
            e.setTexture(inTex, index: 0); e.setTexture(outTex, index: 1); e.setSamplerState(samp, index: 0)
            e.dispatchThreadgroups(MTLSize(width: 30, height: 34, depth: 1), threadsPerThreadgroup: MTLSize(width: 128, height: 1, depth: 1))
            e.endEncoding(); c.commit(); c.waitUntilCompleted()
            if i >= 2 { t.append((c.gpuEndTime - c.gpuStartTime) * 1000) }
        }
        t.sort()
        var o = [UInt32](repeating: 0, count: 1920 * 1080)
        o.withUnsafeMutableBytes { outTex.getBytes($0.baseAddress!, bytesPerRow: 1920 * 4, from: MTLRegionMake2D(0, 0, 1920, 1080), mipmapLevel: 0) }
        var cmp = "reference"
        if let r = ref { let d = zip(r, o).filter { $0 != $1 }.count; cmp = d == 0 ? "output identical" : "OUTPUT DIFFERS in \(d) pixels" } else { ref = o }
        if let e = expect, ref != nil, cmp == "reference" {
            let d = zip(e, o).filter { $0 != $1 }.count
            cmp += d == 0 ? " (equals the game's own output for that frame)" : " (differs from the game's dumped output in \(d) pixels)"
        }
        let distinct = Set(o).count
        let sat = o.filter { ($0 & 0x7FF) == 0x7C0 || ($0 & 0x7FF) == 0 }.count
        print(String(format: "%-28@ median %6.3f ms  min %6.3f  tg mem %5d B  %@  (distinct pixels %d, red zero/inf %d of %d)",
                     (path as NSString).lastPathComponent as NSString, t[t.count / 2], t[0], p.staticThreadgroupMemoryLength, cmp as NSString, distinct, sat, o.count))
    }
} else {
    guard let l = lib(CommandLine.arguments[2]), let p = try? dev.makeComputePipelineState(function: l.makeFunction(name: "unit")!) else { exit(1) }
    let n = 128 * 4096
    let names = (try! String(contentsOfFile: (CommandLine.arguments[2] as NSString).deletingLastPathComponent + "/variants.txt", encoding: .utf8)).split(separator: "\n").map(String.init)
    var rng = RNG(s: 99)
    var totalBad = [Int](repeating: 0, count: names.count), total = 0
    // value classes for the 16 halves a lane holds
    let classes: [(String, (inout RNG) -> UInt16)] = [
        ("any bit pattern", { UInt16(truncatingIfNeeded: $0.next()) }),
        ("normal, |x| in [2^-4, 2)", { r in let v = r.next(); return UInt16((v & 0x8000) | (0x2C00 + (v >> 16) % 0x1400)) }),
        ("small and subnormal", { r in let v = r.next(); return UInt16((v & 0x8000) | ((v >> 16) % 0x0C00)) }),
        ("large, overflows", { r in let v = r.next(); return UInt16((v & 0x8000) | (0x7000 + (v >> 16) % 0x0C00)) }),
        ("mixed with inf/nan/zero", { r in let v = r.next(); let k = v % 16; return k == 0 ? 0x7C00 : k == 1 ? 0xFC00 : k == 2 ? 0x7E00 : k == 3 ? 0 : k == 4 ? 0x8000 : UInt16(truncatingIfNeeded: v >> 8) }),
        ("near fp16 ties (sums of few bits)", { r in let v = r.next(); return UInt16((v & 0x8000) | (0x3800 + ((v >> 16) & 0x0C00)) | ((v >> 8) & 0x3)) }),
    ]
    for (cname, gen) in classes {
        var inp = [UInt32](repeating: 0, count: n * 8)
        for i in 0..<inp.count { inp[i] = UInt32(gen(&rng)) | (UInt32(gen(&rng)) << 16) }
        let ib = dev.makeBuffer(bytes: inp, length: inp.count * 4, options: .storageModeShared)!
        let ob = dev.makeBuffer(length: n * 24 * 4, options: .storageModeShared)!
        let c = q.makeCommandBuffer()!; let e = c.makeComputeCommandEncoder()!
        e.setComputePipelineState(p); e.setBuffer(ib, offset: 0, index: 0); e.setBuffer(ob, offset: 0, index: 1)
        e.dispatchThreadgroups(MTLSize(width: n / 128, height: 1, depth: 1), threadsPerThreadgroup: MTLSize(width: 128, height: 1, depth: 1))
        e.endEncoding(); c.commit(); c.waitUntilCompleted()
        let o = ob.contents().bindMemory(to: UInt32.self, capacity: n * 24)
        var bad = [Int](repeating: 0, count: names.count), lanes = Set<UInt32>(), sgs = Set<UInt32>(), vals = Set<UInt32>()
        for t in 0..<n {
            for v in 0..<names.count where o[t * 24] != o[t * 24 + 2 + 2 * v] || o[t * 24 + 1] != o[t * 24 + 3 + 2 * v] { bad[v] += 1 }
            vals.insert(o[t * 24]); lanes.insert(o[t * 24 + 22]); sgs.insert(o[t * 24 + 23])
        }
        total += n; for v in 0..<names.count { totalBad[v] += bad[v] }
        print(String(format: "unit %-34@ lanes %d  distinct results %d  mismatches %@  (lane ids %d, simdgroup ids %d)", cname as NSString, n, vals.count,
                     zip(names, bad).map { "\($0) \($1)" }.joined(separator: ", ") as NSString, lanes.count, sgs.count))
    }
    print("unit total: \(total) lane results (4 halves each); mismatches: " + zip(names, totalBad).map { "\($0) \($1)" }.joined(separator: ", "))
}
