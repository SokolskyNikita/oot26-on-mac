// oslogtap.dylib: interposes _os_log_impl and prints, to stderr, every os_log message from Metal whose format
// contains "compil", with %@ / %s arguments decoded in-process (so <private> values are visible).
// Use: DYLD_INSERT_LIBRARIES=./oslogtap.dylib MTL_LOG_COMPILE_STATS=3 ./mcdiag ...
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <dlfcn.h>
#include <os/log.h>
#include <CoreFoundation/CoreFoundation.h>
extern void _os_log_impl(void *dso, os_log_t log, os_log_type_t type, const char *format, uint8_t *buf, uint32_t size);
static void my_os_log_impl(void *dso, os_log_t log, os_log_type_t type, const char *format, uint8_t *buf, uint32_t size) {
    if (format && strstr(format, "ompil")) {
        fprintf(stderr, "[oslog] %s\n", format);
        uint32_t i = 2, n = size > 1 ? buf[1] : 0;
        for (uint32_t a = 0; a < n && i + 2 <= size; a++) {
            uint8_t desc = buf[i], sz = buf[i + 1]; uint8_t *d = buf + i + 2; int kind = desc >> 4;
            if (kind == 4 && sz == 8) { // object
                CFTypeRef o; memcpy(&o, d, 8);
                CFStringRef s = o ? CFCopyDescription(o) : NULL; char tmp[65536] = "(null)";
                if (s) { CFStringGetCString(s, tmp, sizeof tmp, kCFStringEncodingUTF8); CFRelease(s); }
                fprintf(stderr, "   arg%u (object): %s\n", a, tmp);
            } else if (kind == 2 && sz == 8) { const char *p; memcpy(&p, d, 8); fprintf(stderr, "   arg%u (string): %s\n", a, p ? p : "(null)"); }
            else if (sz == 8 && kind == 0) { double v; uint64_t u; memcpy(&v, d, 8); memcpy(&u, d, 8); fprintf(stderr, "   arg%u (scalar8): %llu / %f\n", a, u, v); }
            else if (sz == 4) { uint32_t u; memcpy(&u, d, 4); fprintf(stderr, "   arg%u (scalar4): %u\n", a, u); }
            i += 2 + sz;
        }
    }
    _os_log_impl(dso, log, type, format, buf, size);
}
__attribute__((used)) static struct { const void *r, *o; } interposers[] __attribute__((section("__DATA,__interpose"))) = {
    { (const void *)my_os_log_impl, (const void *)_os_log_impl } };
