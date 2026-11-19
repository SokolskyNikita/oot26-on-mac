// xref: find code in Metal.framework that loads the address of given C strings (ADRP + ADD pairs). Read-only.
// Usage: xref STRING...   prints the instruction address and nearest symbol for each reference.
import Foundation
import MachO
import Metal
_ = MTLCreateSystemDefaultDevice()
var hdr: UnsafePointer<mach_header_64>? = nil
for i in 0..<_dyld_image_count() where String(cString: _dyld_get_image_name(i)).hasSuffix("/Metal.framework/Versions/A/Metal") {
    hdr = UnsafeRawPointer(_dyld_get_image_header(i)!).assumingMemoryBound(to: mach_header_64.self)
}
guard let h = hdr else { print("no Metal"); exit(1) }
var csz: UInt = 0, tsz: UInt = 0
let cstr = getsectiondata(h, "__TEXT", "__cstring", &csz)!
let text = getsectiondata(h, "__TEXT", "__text", &tsz)!
for want in CommandLine.arguments.dropFirst() {
    var addrs: [UInt] = []
    var start = 0
    for j in 0..<Int(csz) where cstr[j] == 0 {
        if j - start == want.utf8.count, String(bytes: UnsafeBufferPointer(start: cstr + start, count: j - start), encoding: .utf8) == want {
            addrs.append(UInt(bitPattern: cstr + start))
        }
        start = j + 1
    }
    for a in addrs {
        print("\(want) @ 0x\(String(a, radix: 16))")
        let ins = UnsafeRawPointer(text).assumingMemoryBound(to: UInt32.self)
        let n = Int(tsz) / 4
        for k in 0..<n {
            let w = ins[k]
            guard w & 0x9F00_0000 == 0x9000_0000 else { continue } // ADRP
            let rd = w & 31
            let immlo = UInt((w >> 29) & 3), immhi = UInt((w >> 5) & 0x7FFFF)
            var imm = Int((immhi << 2) | immlo); if imm & (1 << 20) != 0 { imm -= 1 << 21 }
            let pc = UInt(bitPattern: ins + k)
            let page = UInt(bitPattern: Int(pc & ~0xFFF) + (imm << 12))
            guard page == a & ~0xFFF else { continue }
            for m in 1...4 where k + m < n {
                let w2 = ins[k + m]
                if w2 & 0xFFC0_0000 == 0x9100_0000, (w2 >> 5) & 31 == rd, page + UInt((w2 >> 10) & 0xFFF) == a {
                    var di = Dl_info(); dladdr(ins + k, &di)
                    let sym = di.dli_sname.map { String(cString: $0) } ?? "?"
                    print("  ref at 0x\(String(pc, radix: 16))  in \(sym)+\(Int(pc) - Int(bitPattern: di.dli_saddr))")
                }
            }
        }
    }
}
