// probe: for each line of FILE, compile a trivial shader with that line as additionalCompilerArguments and report.
import Metal
import Foundation
let dev = MTLCreateSystemDefaultDevice()!
let src = "#include <metal_stdlib>\nusing namespace metal;\nfragment float4 NAME(float4 p [[position]]) { return float4(p.x); }\n"
var n = 0
for line in try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8).split(separator: "\n") {
    let o = MTLCompileOptions(); o.languageVersion = .version4_0
    o.setValue(String(line), forKey: "additionalCompilerArguments")
    n += 1
    do { _ = try dev.makeLibrary(source: src.replacingOccurrences(of: "NAME", with: "p\(n)"), options: o); print("OK\t\(line)") }
    catch { let e = "\(error)"; let m = e.range(of: "error: ").map { String(e[$0.upperBound...].prefix(70)) } ?? String(e.prefix(90)); print("ERR\t\(line)\t\(m.replacingOccurrences(of: "\n", with: " "))") }
}
