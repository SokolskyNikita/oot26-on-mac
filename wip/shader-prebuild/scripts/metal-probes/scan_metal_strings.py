import ctypes, re, struct, sys
ctypes.CDLL('/System/Library/Frameworks/Metal.framework/Metal')
d = ctypes.CDLL(None)
d._dyld_image_count.restype = ctypes.c_uint32
d._dyld_get_image_name.restype = ctypes.c_char_p
d._dyld_get_image_header.restype = ctypes.c_void_p
d._dyld_get_image_vmaddr_slide.restype = ctypes.c_long
want = re.compile(sys.argv[1])
for i in range(d._dyld_image_count()):
    name = d._dyld_get_image_name(i).decode()
    if not want.search(name): continue
    hdr = d._dyld_get_image_header(i); slide = d._dyld_get_image_vmaddr_slide(i)
    ncmds = struct.unpack_from('<I', ctypes.string_at(hdr, 32), 16)[0]; off = 32
    out=[]
    for _ in range(ncmds):
        cmd, size = struct.unpack('<II', ctypes.string_at(hdr + off, 8))
        if cmd == 0x19:
            seg = ctypes.string_at(hdr + off, size)
            nsects = struct.unpack_from('<I', seg, 64)[0]
            for s in range(nsects):
                sec = seg[72 + 80*s: 72 + 80*(s+1)]; sname = sec[:16].rstrip(b'\0')
                addr, sz = struct.unpack_from('<QQ', sec, 32)
                if sname in (b'__cstring', b'__oslogstring', b'__const') and sz < 50_000_000:
                    data = ctypes.string_at(addr + slide, sz)
                    for m in re.finditer(rb'[\x20-\x7e]{5,}', data): out.append(m.group().decode())
        off += size
    print('##', name, len(out))
    for s in out: print(s)
