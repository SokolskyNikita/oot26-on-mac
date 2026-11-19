// mtlstrings: dlopen Metal (+ given extra images) and print every C string in __TEXT,__cstring of every
// loaded image whose path contains a filter, one "image<TAB>string" per line. Read-only.
// Usage: mtlstrings [extra dylib/framework paths to dlopen...]
import Foundation
import MachO
import Metal
_ = MTLCreateSystemDefaultDevice()
for p in CommandLine.arguments.dropFirst() { if dlopen(p, RTLD_LAZY) == nil { FileHandle.standardError.write("dlopen failed: \(p)\n".data(using: .utf8)!) } }
let filters = ["Metal", "MTL", "GPU", "AGX", "IOAccel"]
for i in 0..<_dyld_image_count() {
    let name = String(cString: _dyld_get_image_name(i))
    guard filters.contains(where: { name.contains($0) }) else { continue }
    let hdr = UnsafeRawPointer(_dyld_get_image_header(i)!).assumingMemoryBound(to: mach_header_64.self)
    for sect in ["__cstring", "__const"] {
        var size: UInt = 0
        guard let p = getsectiondata(hdr, "__TEXT", sect, &size) else { continue }
        var start = 0
        let n = Int(size)
        for j in 0..<n where p[j] == 0 {
            if j - start >= 4, let s = String(bytes: UnsafeBufferPointer(start: p + start, count: j - start), encoding: .utf8) {
                print("\((name as NSString).lastPathComponent)\t\(s.replacingOccurrences(of: "\n", with: "\\n"))")
            }
            start = j + 1
        }
    }
}
