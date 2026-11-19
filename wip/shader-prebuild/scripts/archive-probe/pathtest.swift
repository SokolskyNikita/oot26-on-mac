// Checks that MTLSetShaderCachePath moves Metal's shader, module and gpuarchiver caches. Usage: pathtest DIR
import Metal
import Foundation
typealias SetF = @convention(c) (NSString) -> Void
typealias GetF = @convention(c) () -> AnyObject?
let h = dlopen("/System/Library/Frameworks/Metal.framework/Metal", RTLD_NOW)
let set = unsafeBitCast(dlsym(h, "MTLSetShaderCachePath")!, to: SetF.self)
set(CommandLine.arguments[1] as NSString)
for n in ["MTLGetShaderCachePath", "MTLGetModulesCachePath", "MTLGetGPUArchiverCachePath"] {
    let g = unsafeBitCast(dlsym(h, n)!, to: GetF.self)
    print(n, g().map { "\($0)" } ?? "nil")
}
if CommandLine.arguments.count > 2 {
    let dev = MTLCreateSystemDefaultDevice()!
    let src = "#include <metal_stdlib>\nusing namespace metal;\nvertex float4 v(uint i [[vertex_id]]) { return float4(i, \(Int.random(in: 0..<1000000)), 0, 1); }\nfragment float4 f() { return 1; }\n"
    let l = try! dev.makeLibrary(source: src, options: nil)
    let d = MTLRenderPipelineDescriptor(); d.vertexFunction = l.makeFunction(name: "v"); d.fragmentFunction = l.makeFunction(name: "f"); d.colorAttachments[0].pixelFormat = .bgra8Unorm
    let a = try! dev.makeBinaryArchive(descriptor: MTLBinaryArchiveDescriptor())
    try! a.addRenderPipelineFunctions(descriptor: d)
    _ = try! dev.makeRenderPipelineState(descriptor: d)
    try! a.serialize(to: URL(fileURLWithPath: CommandLine.arguments[2]))
    print("archive written")
}
