// dumpstr: every C string in the Metal, compiler and GPU driver images, one per line with the image name.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <mach-o/dyld.h>
#import <mach-o/getsect.h>
#import <dlfcn.h>
int main(void) { @autoreleasepool {
    (void)MTLCreateSystemDefaultDevice();
    dlopen("/System/Library/PrivateFrameworks/MTLCompiler.framework/MTLCompiler", RTLD_LAZY);
    dlopen("/System/Library/PrivateFrameworks/AGXCompilerCore.framework/AGXCompilerCore", RTLD_LAZY);
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const char *name = _dyld_get_image_name(i);
        if (!strstr(name, "Metal") && !strstr(name, "MTL") && !strstr(name, "AGX") && !strstr(name, "GPUCompiler")) continue;
        const char *base = strrchr(name, '/') + 1;
        const struct mach_header_64 *mh = (const struct mach_header_64 *)_dyld_get_image_header(i);
        const char *secs[] = {"__cstring", "__objc_methname"};
        for (int s = 0; s < 2; s++) {
            unsigned long size = 0; const char *sec = (const char *)getsectiondata(mh, "__TEXT", secs[s], &size);
            for (unsigned long o = 0; sec && o < size;) { size_t len = strnlen(sec + o, size - o); if (len >= 4 && len < 120) printf("%s\t%.*s\n", base, (int)len, sec + o); o += len + 1; }
        }
    }
} return 0; }
