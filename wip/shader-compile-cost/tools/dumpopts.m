// dumpopts: list MTLCompileOptions properties (public and private) and environment-variable-like strings in Apple's
// Metal compiler images. Read-only inspection of loaded system libraries.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#import <mach-o/dyld.h>
#import <mach-o/getsect.h>
#import <dlfcn.h>
static void props(const char *cls) {
    Class c = objc_getClass(cls); if (!c) { printf("class %s: not found\n", cls); return; }
    unsigned n = 0; objc_property_t *p = class_copyPropertyList(c, &n);
    printf("== %s: %u properties\n", cls, n);
    for (unsigned i = 0; i < n; i++) printf("   %s   [%s]\n", property_getName(p[i]), property_getAttributes(p[i]));
    unsigned m = 0; Method *ms = class_copyMethodList(c, &m);
    printf("   methods:");
    for (unsigned i = 0; i < m; i++) printf(" %s", sel_getName(method_getName(ms[i])));
    printf("\n");
}
int main(int argc, char **argv) {
    @autoreleasepool {
        id<MTLDevice> d = MTLCreateSystemDefaultDevice(); (void)d;
        props("MTLCompileOptions"); props("MTLRenderPipelineDescriptorInternal"); props("MTLBinaryArchiveDescriptor");
        const char *extra[] = {"/System/Library/PrivateFrameworks/MTLCompiler.framework/MTLCompiler",
            "/System/Library/PrivateFrameworks/GPUCompiler.framework/GPUCompiler",
            "/System/Library/PrivateFrameworks/GPUCompiler.framework/Versions/32023/Libraries/libGPUCompilerImplLazy.dylib",
            "/System/Library/PrivateFrameworks/AGXCompilerCore.framework/AGXCompilerCore",
            "/System/Library/PrivateFrameworks/AGXCompilerConnection.framework/AGXCompilerConnection"};
        for (int i = 0; i < 5; i++) if (!dlopen(extra[i], RTLD_LAZY)) printf("dlopen failed: %s\n", extra[i]);
        NSRegularExpression *re = [NSRegularExpression regularExpressionWithPattern:@"^(MTL|METAL|AGX|AGC|GPU|AIR|FS|MTLCOMPILER|GPUCOMPILER)_[A-Z0-9_]{3,}$" options:0 error:nil];
        for (uint32_t i = 0; i < _dyld_image_count(); i++) {
            const char *name = _dyld_get_image_name(i);
            if (!strstr(name, "Metal") && !strstr(name, "MTL") && !strstr(name, "AGX") && !strstr(name, "GPUCompiler")) continue;
            const struct mach_header_64 *mh = (const struct mach_header_64 *)_dyld_get_image_header(i);
            unsigned long size = 0; const char *sec = (const char *)getsectiondata(mh, "__TEXT", "__cstring", &size);
            NSMutableOrderedSet *found = [NSMutableOrderedSet new];
            for (unsigned long o = 0; sec && o < size;) {
                size_t len = strnlen(sec + o, size - o);
                if (len >= 6 && len < 80) {
                    NSString *s = [[NSString alloc] initWithBytes:sec + o length:len encoding:NSASCIIStringEncoding];
                    if (s && [re firstMatchInString:s options:0 range:NSMakeRange(0, s.length)]) [found addObject:s];
                }
                o += len + 1;
            }
            if (found.count) printf("== %s: %lu candidate names\n   %s\n", name, (unsigned long)found.count, [[found.array componentsJoinedByString:@" "] UTF8String]);
        }
    }
    return 0;
}
