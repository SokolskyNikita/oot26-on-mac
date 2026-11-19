// getenvlog.dylib: logs getenv() names containing MTL/FS_/AGX/METAL/GPU and every CFPreferences app-value read,
// with the calling image, to stderr. Use: DYLD_INSERT_LIBRARIES=./getenvlog.dylib ./mcdiag ...
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <CoreFoundation/CoreFoundation.h>
static const char *caller(void *ra) {
    Dl_info di; if (dladdr(ra, &di) && di.dli_fname) { const char *s = strrchr(di.dli_fname, '/'); return s ? s + 1 : di.dli_fname; } return "?";
}
static void cfs(CFStringRef s, char *buf, size_t n) { buf[0] = 0; if (s) CFStringGetCString(s, buf, n, kCFStringEncodingUTF8); }
static char *my_getenv(const char *n) {
    char *v = getenv(n);
    if (n && (strstr(n, "MTL") || strstr(n, "FS_") || strstr(n, "AGX") || strstr(n, "METAL") || strstr(n, "GPU")))
        fprintf(stderr, "[getenv] %s = %s  (from %s)\n", n, v ? v : "(unset)", caller(__builtin_return_address(0)));
    return v;
}
static CFPropertyListRef my_copy(CFStringRef k, CFStringRef app) {
    CFPropertyListRef v = CFPreferencesCopyAppValue(k, app);
    char kb[256], ab[256]; cfs(k, kb, sizeof kb); cfs(app, ab, sizeof ab);
    fprintf(stderr, "[cfprefs copy] %s / %s = %s  (from %s)\n", ab, kb, v ? "SET" : "(unset)", caller(__builtin_return_address(0)));
    return v;
}
static Boolean my_bool(CFStringRef k, CFStringRef app, Boolean *ok) {
    Boolean v = CFPreferencesGetAppBooleanValue(k, app, ok);
    char kb[256], ab[256]; cfs(k, kb, sizeof kb); cfs(app, ab, sizeof ab);
    fprintf(stderr, "[cfprefs bool] %s / %s = %d  (from %s)\n", ab, kb, v, caller(__builtin_return_address(0)));
    return v;
}
static CFIndex my_int(CFStringRef k, CFStringRef app, Boolean *ok) {
    CFIndex v = CFPreferencesGetAppIntegerValue(k, app, ok);
    char kb[256], ab[256]; cfs(k, kb, sizeof kb); cfs(app, ab, sizeof ab);
    fprintf(stderr, "[cfprefs int] %s / %s = %ld  (from %s)\n", ab, kb, (long)v, caller(__builtin_return_address(0)));
    return v;
}
__attribute__((used)) static struct { const void *r, *o; } interposers[] __attribute__((section("__DATA,__interpose"))) = {
    { (const void *)my_getenv, (const void *)getenv },
    { (const void *)my_copy, (const void *)CFPreferencesCopyAppValue },
    { (const void *)my_bool, (const void *)CFPreferencesGetAppBooleanValue },
    { (const void *)my_int, (const void *)CFPreferencesGetAppIntegerValue },
};
