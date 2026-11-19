// libverifyhook.dylib: loaded into Lichii with DYLD_INSERT_LIBRARIES by run.py. Two jobs, no window focus needed:
//
// 1. Frame clock. Swizzles -[CAMetalLayer nextDrawable] (MoltenVK takes one drawable per presented swapchain image)
//    and appends the time of each call, as uint64 nanoseconds of CLOCK_UPTIME_RAW, to $VERIFY_DIR/frames.bin.
//    The frame count is what run.py schedules inputs and screenshots by, so a route lasts the same number of game
//    frames on a fast build and a slow one.
// 2. Screenshots. A process may capture its own windows without the Screen Recording permission, so this captures
//    Lichii's main window (CGWindowListCreateImage on our own window id) while it sits behind other windows.
//
// Control: UDP 127.0.0.1:$VERIFY_PORT, one command per datagram, one reply:
//   count        -> "<frames so far>"
//   shot <path>  -> "ok <frame> <w>x<h>" after writing a PNG at <path>, or "err <why>"
#import <Cocoa/Cocoa.h>
#import <QuartzCore/QuartzCore.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <objc/runtime.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static _Atomic uint64_t g_count;
static int g_fd = -1;
static IMP g_orig_next;

static id hooked_nextDrawable(id self, SEL cmd) {
    id drawable = ((id (*)(id, SEL))g_orig_next)(self, cmd);
    uint64_t t = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    if (g_fd >= 0) write(g_fd, &t, sizeof t);
    atomic_fetch_add(&g_count, 1);
    return drawable;
}

typedef CGImageRef (*CreateImageFn)(CGRect, uint32_t, uint32_t, uint32_t);

// Our largest on-screen-layer window: the main window (Lichii's menus and dialogs are smaller).
static uint32_t main_window_id(void) {
    CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID);
    uint32_t best = 0;
    double best_area = 0;
    pid_t me = getpid();
    for (CFIndex i = 0; list && i < CFArrayGetCount(list); i++) {
        NSDictionary *w = (__bridge NSDictionary *)CFArrayGetValueAtIndex(list, i);
        if ([w[(id)kCGWindowOwnerPID] intValue] != me || [w[(id)kCGWindowLayer] intValue] != 0) continue;
        CGRect b;
        CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)w[(id)kCGWindowBounds], &b);
        if (b.size.width * b.size.height > best_area) {
            best_area = b.size.width * b.size.height;
            best = [w[(id)kCGWindowNumber] unsignedIntValue];
        }
    }
    if (list) CFRelease(list);
    return best;
}

static NSString *shot(NSString *path) {
    static CreateImageFn create;
    if (!create) create = (CreateImageFn)dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
    if (!create) return @"err no CGWindowListCreateImage";
    uint32_t wid = main_window_id();
    if (!wid) return @"err no window";
    uint64_t frame = atomic_load(&g_count);
    // 1<<3 kCGWindowListOptionIncludingWindow; 1 BoundsIgnoreFraming | 16 NominalResolution (points, not Retina px)
    CGImageRef img = create(CGRectNull, 1 << 3, wid, 1 | 16);
    if (!img) return @"err capture returned nothing";
    CGImageDestinationRef dst = CGImageDestinationCreateWithURL(
        (__bridge CFURLRef)[NSURL fileURLWithPath:path], (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL);
    NSString *reply;
    if (dst) {
        CGImageDestinationAddImage(dst, img, NULL);
        bool ok = CGImageDestinationFinalize(dst);
        CFRelease(dst);
        reply = ok ? [NSString stringWithFormat:@"ok %llu %zux%zu", frame, CGImageGetWidth(img), CGImageGetHeight(img)]
                   : @"err png write failed";
    } else {
        reply = @"err cannot open png";
    }
    CGImageRelease(img);
    return reply;
}

static int bind_control(int port) {
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port)};
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s, (struct sockaddr *)&a, sizeof a) != 0) {
        close(s);
        return -1;
    }
    return s;
}

static void *server(void *arg) {
    int s = (int)(intptr_t)arg;
    char buf[2048];
    for (;;) {
        struct sockaddr_in from;
        socklen_t fl = sizeof from;
        ssize_t n = recvfrom(s, buf, sizeof buf - 1, 0, (struct sockaddr *)&from, &fl);
        if (n <= 0) continue;
        buf[n] = 0;
        @autoreleasepool {
            NSString *cmd = [NSString stringWithUTF8String:buf], *reply;
            if ([cmd isEqualToString:@"count"]) {
                reply = [NSString stringWithFormat:@"%llu", atomic_load(&g_count)];
            } else if ([cmd hasPrefix:@"shot "]) {
                reply = shot([cmd substringFromIndex:5]);
            } else if ([cmd hasPrefix:@"title "]) {
                // Append " ‖ <text>" to every window's own title (replacing an earlier suffix), so a run can say
                // which session, scenario and attempt it is.
                NSString *suffix = [cmd substringFromIndex:6];
                dispatch_async(dispatch_get_main_queue(), ^{
                    for (NSWindow *w in NSApp.windows) {
                        NSString *t = w.title ?: @"";
                        if (![t hasPrefix:@"Lichii"]) continue;   // the main window only, not dialogs
                        NSRange r = [t rangeOfString:@" \u2016 "];
                        if (r.location != NSNotFound) t = [t substringToIndex:r.location];
                        // Keep only "Lichii | <build>" of Lichii's own title (drop compiler, game name, version).
                        NSArray *parts = [t componentsSeparatedByString:@" | "];
                        if (parts.count > 2) t = [[parts subarrayWithRange:NSMakeRange(0, 2)] componentsJoinedByString:@" | "];
                        if (t.length) w.title = [NSString stringWithFormat:@"%@ \u2016 %@", t, suffix];
                    }
                });
                reply = @"ok";
            } else {
                reply = @"err unknown command";
            }
            const char *r = reply.UTF8String;
            sendto(s, r, strlen(r), 0, (struct sockaddr *)&from, fl);
        }
    }
}

__attribute__((constructor)) static void init(void) {
    const char *dir = getenv("VERIFY_DIR"), *port = getenv("VERIFY_PORT");
    // Keep the hook out of anything Lichii starts (it runs helper processes).
    unsetenv("DYLD_INSERT_LIBRARIES");
    if (!dir || !port) return;
    int s = bind_control(atoi(port));
    if (s < 0) {
        fprintf(stderr, "[verifyhook] cannot bind 127.0.0.1:%s, hook off in pid %d\n", port, getpid());
        return;
    }
    char path[4096];
    snprintf(path, sizeof path, "%s/frames.bin", dir);
    g_fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
    Method m = class_getInstanceMethod([CAMetalLayer class], @selector(nextDrawable));
    g_orig_next = method_setImplementation(m, (IMP)hooked_nextDrawable);
    pthread_t t;
    pthread_create(&t, NULL, server, (void *)(intptr_t)s);
    pthread_detach(t);
    fprintf(stderr, "[verifyhook] frame clock on, control on 127.0.0.1:%s (pid %d)\n", port, getpid());
}
