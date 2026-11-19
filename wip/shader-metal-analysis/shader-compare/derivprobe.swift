// derivprobe: does an implicit-LOD texture sample inside an `if` give the same result as an unconditional one on this GPU?
import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!; let q = dev.makeCommandQueue()!
let W = 512, H = 512
let src = """
#include <metal_stdlib>
using namespace metal;
struct V { float4 pos [[position]]; float2 uv; };
vertex V vs(uint vid [[vertex_id]]) { V o; float2 p = float2(vid == 1 ? 2.0 : 0.0, vid == 2 ? 2.0 : 0.0); o.pos = float4(p * 2.0 - 1.0, 0.5, 1.0); o.uv = p * float2(3.0, 7.0); return o; }
struct U { uint flag; };
fragment float4 fs(V in [[stage_in]], texture2d<float> t, sampler s, constant U& u [[buffer(0)]]) {
    float2 uv = in.uv * (1.0 + in.uv.x);              // LOD varies over the screen
    float a = t.sample(s, uv).x;                       // reference: unconditional
    float b = -1.0; if (u.flag != 0u) { b = t.sample(s, uv + 0.25).x; }                                  // uniform condition
    bool px = ((uint(in.pos.x) + uint(in.pos.y)) & 1u) == 0u;                                     // differs inside every 2x2 quad
    float c = -1.0; if (px) { c = t.sample(s, uv + 0.5).x; }
    bool blk = ((uint(in.pos.x) / 2u + uint(in.pos.y) / 2u) & 1u) == 0u;                          // per-pixel computed, same within a quad
    float d = -1.0; if (blk) { d = t.sample(s, uv + 0.75).x; }
    return float4(a, b, c, d);
}
"""
let lib = try! dev.makeLibrary(source: src, options: nil)
let pd = MTLRenderPipelineDescriptor(); pd.vertexFunction = lib.makeFunction(name: "vs"); pd.fragmentFunction = lib.makeFunction(name: "fs"); pd.colorAttachments[0].pixelFormat = .rgba32Float
let pso = try! dev.makeRenderPipelineState(descriptor: pd)
let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .r32Float, width: 256, height: 256, mipmapped: true); td.usage = [.shaderRead]
let tex = dev.makeTexture(descriptor: td)!
for l in 0..<tex.mipmapLevelCount { let w = max(1, 256 >> l); var px = [Float](repeating: Float(l), count: w * w); tex.replace(region: MTLRegionMake2D(0, 0, w, w), mipmapLevel: l, withBytes: &px, bytesPerRow: w * 4) } // each mip level stores its own index
let sd = MTLSamplerDescriptor(); sd.minFilter = .linear; sd.magFilter = .linear; sd.mipFilter = .linear; sd.sAddressMode = .repeat; sd.tAddressMode = .repeat
let samp = dev.makeSamplerState(descriptor: sd)!
let rt = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: W, height: H, mipmapped: false); rt.usage = [.renderTarget]; rt.storageMode = .shared
let target = dev.makeTexture(descriptor: rt)!
var flag: UInt32 = 1
let pass = MTLRenderPassDescriptor(); pass.colorAttachments[0].texture = target; pass.colorAttachments[0].loadAction = .clear; pass.colorAttachments[0].storeAction = .store
let cb = q.makeCommandBuffer()!, e = cb.makeRenderCommandEncoder(descriptor: pass)!; e.setRenderPipelineState(pso); e.setFragmentTexture(tex, index: 0); e.setFragmentSamplerState(samp, index: 0); e.setFragmentBytes(&flag, length: 4, index: 0)
e.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3); e.endEncoding(); cb.commit(); cb.waitUntilCompleted()
var px = [Float](repeating: 0, count: W * H * 4); px.withUnsafeMutableBytes { target.getBytes($0.baseAddress!, bytesPerRow: W * 16, from: MTLRegionMake2D(0, 0, W, H), mipmapLevel: 0) }
var lodMin: Float = 99, lodMax: Float = 0
for (ch, name) in [(1, "uniform condition"), (2, "condition differs inside each 2x2 quad"), (3, "per-pixel condition, equal within a quad")] {
    var taken = 0, same = 0; var worst: Float = 0
    for i in 0..<(W * H) { let a = px[i * 4], v = px[i * 4 + ch]; lodMin = min(lodMin, a); lodMax = max(lodMax, a); if v < 0 { continue }; taken += 1; if v == a { same += 1 }; worst = max(worst, abs(v - a)) }
    print(String(format: "%-42@ taken %6d px, identical to unconditional %6d, worst mip-level error %.3f", name as NSString, taken, same, worst))
}
print("mip level range in the reference: \(lodMin) .. \(lodMax)")
