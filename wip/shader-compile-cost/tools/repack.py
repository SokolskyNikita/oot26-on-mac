# repack.py ORIG.metallib NEW.bc OUT.metallib: swap the bitcode of a one-function metallib, fixing sizes, offsets, hash.
import struct, hashlib, sys
d = bytearray(open(sys.argv[1], "rb").read()); newbc = open(sys.argv[2], "rb").read()
bc_off, bc_sz = struct.unpack_from("<2Q", d, 0x18 + 48)
delta = len(newbc) - bc_sz
n = bytearray(d[:bc_off]) + newbc + d[bc_off + bc_sz:]
struct.pack_into("<Q", n, 0x10, len(n)); struct.pack_into("<Q", n, 0x18 + 56, len(newbc))
j = n.find(b"MDSZ"); struct.pack_into("<Q", n, j + 6, len(newbc))
k = n.find(b"HASH"); n[k + 6:k + 38] = hashlib.sha256(newbc).digest()
for tag in (b"HDYN", b"RLST"):
    p = n.find(tag, 0, bc_off)
    if p != -1:
        off = struct.unpack_from("<Q", n, p + 6)[0]; struct.pack_into("<Q", n, p + 6, off + delta)
open(sys.argv[3], "wb").write(n)
