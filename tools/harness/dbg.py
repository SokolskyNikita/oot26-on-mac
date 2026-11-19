"""Tiny client for Lichii's debug server (EDEN_NX2_DEBUG_SERVER): one JSON-lines request per call."""
import json, socket, sys
def call(method, timeout=120, **params):
    s = socket.create_connection(("127.0.0.1", 6545), timeout=timeout)
    s.sendall((json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk: break
        buf += chunk
    s.close()
    r = json.loads(buf)
    if "error" in r: raise RuntimeError(f"{method}: {r['error']}")
    return r["result"]
MAIN = 0x80822000  # set per boot from eden_log "Module main loaded at" (ASLR moves it every boot)
def kab(addr): return MAIN + (addr - 0x80020000)   # Kabosune absolute -> our guest VA
def u64(a): return int(call("read_memory", address=hex(a), size=8, **{"as": "u64"})["u64"][0], 16)
def f32s(a, n): return [float(v) for v in call("read_memory", address=hex(a), size=4*n, **{"as": "f32"})["f32"]]
if __name__ == "__main__":
    print(json.dumps(call(sys.argv[1], **json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")), indent=1))
