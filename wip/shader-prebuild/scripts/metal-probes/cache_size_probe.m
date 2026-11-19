// probe CACHE_DIR FIRST COUNT [UNROLL]
// Points Metal's shader cache at CACHE_DIR (MTLSetShaderCachePath, before any device), then compiles COUNT
// throwaway compute kernels with salts FIRST..FIRST+COUNT-1 and builds a pipeline for each. Prints how many
// came back fast (cache hits) and the total time. MTL_SHADER_CACHE_SIZE is taken from the environment as is.
// Written only for the cache-size question in wip/shader-prebuild/metal-shader-cache.md; writes nothing outside CACHE_DIR by design.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <dlfcn.h>
#include <mach/mach_time.h>

typedef void (*SetPath)(NSString *);
typedef NSString *(*GetPath)(void);

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc < 4) { fprintf(stderr, "usage: probe DIR FIRST COUNT [UNROLL]\n"); return 2; }
        NSString *dir = [NSString stringWithUTF8String:argv[1]];
        long first = atol(argv[2]), count = atol(argv[3]), unroll = argc > 4 ? atol(argv[4]) : 64;
        void *metal = dlopen("/System/Library/Frameworks/Metal.framework/Metal", RTLD_NOW);
        SetPath set = (SetPath)dlsym(metal, "MTLSetShaderCachePath");
        GetPath get = (GetPath)dlsym(metal, "MTLGetShaderCachePath");
        if (!set || !get) { fprintf(stderr, "no cache-path SPI\n"); return 3; }
        set(dir);
        if (![get() isEqualToString:dir]) { fprintf(stderr, "cache path not taken: %s\n", [get() UTF8String]); return 4; }
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        mach_timebase_info_data_t tb; mach_timebase_info(&tb);
        long fast = 0; double total = 0, slowest = 0;
        for (long i = first; i < first + count; i++) {
            @autoreleasepool {
                NSMutableString *src = [NSMutableString stringWithString:
                    @"#include <metal_stdlib>\nusing namespace metal;\nkernel void k(device float *o [[buffer(0)]], uint t [[thread_position_in_grid]]) {\n float a = o[t];\n"];
                for (long j = 0; j < unroll; j++)
                    [src appendFormat:@" a = fma(a, %ld.%03ldf, sin(a * %ld.0f));\n", i + 1, j, j + 3];
                [src appendString:@" o[t] = a;\n}\n"];
                uint64_t t0 = mach_absolute_time();
                NSError *err = nil;
                id<MTLLibrary> lib = [dev newLibraryWithSource:src options:nil error:&err];
                id<MTLFunction> fn = [lib newFunctionWithName:@"k"];
                id<MTLComputePipelineState> ps = fn ? [dev newComputePipelineStateWithFunction:fn error:&err] : nil;
                double ms = (mach_absolute_time() - t0) * (double)tb.numer / tb.denom / 1e6;
                if (!ps) { fprintf(stderr, "salt %ld failed: %s\n", i, [[err description] UTF8String]); return 5; }
                total += ms; if (ms > slowest) slowest = ms; if (ms < 3.0) fast++;
            }
        }
        printf("salts %ld..%ld: %ld fast (<3 ms) of %ld, total %.0f ms, slowest %.1f ms, size env %s\n", first,
               first + count - 1, fast, count, total, slowest, getenv("MTL_SHADER_CACHE_SIZE") ?: "(unset)");
    }
    return 0;
}
