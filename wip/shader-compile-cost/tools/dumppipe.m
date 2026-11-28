// dumppipe: types of the private pipeline-descriptor settings (method signatures only; no compile).
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
int main(void) { @autoreleasepool {
    (void)MTLCreateSystemDefaultDevice();
    const char *classes[] = {"MTLRenderPipelineDescriptorInternal", "MTLComputePipelineDescriptorInternal", "MTLRenderPipelineDescriptor", "MTLCompileOptions", "MTLMeshRenderPipelineDescriptorInternal"};
    for (int c = 0; c < 5; c++) {
        Class k = objc_getClass(classes[c]); if (!k) { printf("%s: missing\n", classes[c]); continue; }
        unsigned m = 0; Method *ms = class_copyMethodList(k, &m);
        printf("== %s\n", classes[c]);
        for (unsigned i = 0; i < m; i++) {
            const char *n = sel_getName(method_getName(ms[i]));
            if (strstr(n, "ompiler") || strstr(n, "SPI") || strstr(n, "rofile") || strstr(n, "imeout") || strstr(n, "pluginData") || strstr(n, "PluginData") || strstr(n, "ptimiz") || strstr(n, "nlin") || strstr(n, "ache") || strstr(n, "rchive") || strstr(n, "ebug") || strstr(n, "tatistic"))
                printf("   %-48s %s\n", n, method_getTypeEncoding(ms[i]));
        }
    }
    id d = [MTLRenderPipelineDescriptor new];
    for (NSString *key in @[@"gpuCompilerSPIOptions", @"driverCompilerOptions", @"profileControl", @"pluginData"]) {
        @try { id v = [d valueForKey:key]; printf("default %s = %s (%s)\n", key.UTF8String, [[v description] UTF8String], v ? object_getClassName(v) : "nil"); }
        @catch (NSException *e) { printf("default %s: %s\n", key.UTF8String, e.reason.UTF8String); }
    }
    @try { printf("compilerTimeoutInSeconds = %s\n", [[[d valueForKey:@"compilerTimeoutInSeconds"] description] UTF8String]); } @catch (NSException *e) { printf("timeout: %s\n", e.reason.UTF8String); }
} return 0; }
