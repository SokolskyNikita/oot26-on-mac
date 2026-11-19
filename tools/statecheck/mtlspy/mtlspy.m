// mtlspy: a library to insert into any Metal program (DYLD_INSERT_LIBRARIES) that logs, for mesh draws of chosen
// pipelines, exactly what Metal was given: the buffers bound to the object (task) and mesh stages, and what a bound
// argument buffer points to. It is how to compare two pipelines that should see the same inputs.
//
//   MTLSPY_OUT=file            log file (default stderr)
//   MTLSPY_SRC_LENS=a,b,...    only pipelines whose MESH function was compiled from MSL of one of these lengths
//                              (characters); empty = every mesh pipeline
//   MTLSPY_HASH=a,b,...        window sizes in bytes hashed from each bound offset (default 256,4096,65536); a
//                              binding does not carry its size, so pick windows no larger than what the shader reads
//   MTLSPY_HEX=n               also print the first n bytes at each bound offset as hex
//   MTLSPY_LIST_COMPUTE=1      list every compute pipeline with its source length (a compute pipeline is logged
//                              like a draw when its source length is in MTLSPY_SRC_LENS)
//   MTLSPY_DUMP_SRC_DIR=dir    write every shader source compiled to dir/src-<length>.metal
//   MTLSPY_MAX=n               draws logged per pipeline (default 4)
//   MTLSPY_ARG_WORDS=n         8-byte words of buffer index 0 to decode as an argument buffer (default 64)
//   MTLSPY_STATE_OUT=file      the Metal half of the Vulkan-to-Metal state check (the Vulkan half is ../vkspy):
//                              one "M" line for EVERY draw of every pipeline with the raster state the encoder holds
//                              at that draw. tag= is the id of the Vulkan draw it belongs to, read from the debug
//                              signposts vkspy inserts ("vkspy:d<id>" before a draw, "vkspy:x" after it); tag=-1 is
//                              a draw MoltenVK made on its own (a clear, a resolve). seq= counts the Metal draws of
//                              one tag. set= has one bit per value set on THIS encoder since it was made
//                              (1 cull, 2 winding, 4 fill, 8 depth clip, 16 stencil reference, 32 depth-stencil
//                              state, 64 depth bias, 128 viewport, 256 scissor); a value whose bit is clear is
//                              Metal's default and prints as 0. rt= is the size of the render target. Enum values
//                              are Metal's own numbers; prim=-1 is a mesh draw.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#import <os/lock.h>

static FILE* gOut;
static os_unfair_lock gLock = OS_UNFAIR_LOCK_INIT;
static char kLen, kName, kMeshLen, kObjLen, kCount;
static NSMutableSet<NSNumber*>* gLens;
static int gMax = 4, gArgWords = 64, gHex = 0, gListCompute = 0;
static size_t gWin[8] = {256, 4096, 65536}; static int gNWin = 3;   // MTLSPY_HASH=a,b,...: bytes hashed from the bound offset
static NSHashTable* gBuffers;   // weak set of every MTLBuffer made by the device
static NSMapTable* gEnc;        // encoder -> state

typedef struct { __unsafe_unretained id<MTLBuffer> buf; NSUInteger off; BOOL bytes; NSUInteger blen; } Slot;
@interface SpyState : NSObject { @public Slot obj[31]; Slot mesh[31]; __unsafe_unretained id pipe; NSMapTable* used;
    float bias[3]; int biasSet; MTLViewport vp; int vpSet; MTLScissorRect sc; int scSet; long clip, cull, winding, fill; unsigned stencilRef[2]; __unsafe_unretained id ds; unsigned setMask; unsigned long rtw, rth; } @end
@implementation SpyState @end

static SpyState* stateFor(id enc) {
    SpyState* s = [gEnc objectForKey:enc];
    if (!s) { s = [SpyState new]; s->used = [[NSMapTable mapTableWithKeyOptions:NSPointerFunctionsOpaqueMemory | NSPointerFunctionsOpaquePersonality valueOptions:NSPointerFunctionsStrongMemory] retain]; [gEnc setObject:s forKey:enc]; }
    return s;
}
static uint64_t fnv(const uint8_t* p, size_t n) { uint64_t h = 1469598103934665603ull; for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 1099511628211ull; } return h; }

static NSMapTable* gUsedNow;   // useResource declarations of the encoder being dumped
static void describe(const char* what, id<MTLBuffer> b, NSUInteger off) {
    const uint8_t* c = (const uint8_t*)[b contents];
    NSUInteger len = [b length];
    fprintf(gOut, "    %s buffer=%p len=%lu off=%lu gpu=0x%llx mode=%lu", what, (void*)b, (unsigned long)len, (unsigned long)off,
            (unsigned long long)[b gpuAddress], (unsigned long)[b storageMode]);
    if (c && off < len) {
        size_t n = len - off;
        for (int i = 0; i < gNWin; i++) { size_t w = n < gWin[i] ? n : gWin[i]; fprintf(gOut, " h%zu=%08x", gWin[i], (unsigned)(fnv(c + off, w) >> 32)); }
        fprintf(gOut, " first=");
        for (size_t i = 0; i < 16 && i < n; i++) fprintf(gOut, "%02x", c[off + i]);
    }
    if (c && off < len && gHex) {
        size_t n = len - off; if (n > (size_t)gHex) n = gHex;
        fprintf(gOut, " hex=");
        for (size_t i = 0; i < n; i++) fprintf(gOut, "%02x", c[off + i]);
    }
    if (gUsedNow) {
        NSNumber* u = [gUsedNow objectForKey:b];
        id<MTLHeap> hp = [b heap];
        NSNumber* hu = hp ? [gUsedNow objectForKey:hp] : nil;
        if (u) fprintf(gOut, " useResource=stages:0x%lx%s", (unsigned long)(u.unsignedLongValue & 0xff), (u.unsignedLongValue & 0x100) ? ",write" : ",read");
        else if (hu) fprintf(gOut, " useHeap=stages:0x%lx", (unsigned long)(hu.unsignedLongValue & 0xff));
        else fprintf(gOut, " useResource=NONE");
    }
    if ([b label]) fprintf(gOut, " label=%s", [[b label] UTF8String]);
    fprintf(gOut, "\n");
}
static void decodeArgs(id<MTLBuffer> b, NSUInteger off) {
    const uint8_t* c = (const uint8_t*)[b contents];
    if (!c) return;
    NSUInteger len = [b length];
    for (int i = 0; i < gArgWords && off + 8 * (i + 1) <= len; i++) {
        uint64_t v; memcpy(&v, c + off + 8 * i, 8);
        if (!v) continue;
        BOOL hit = NO;
        for (id<MTLBuffer> o in gBuffers) {
            uint64_t g = [o gpuAddress];
            if (g && v >= g && v < g + [o length]) {
                char w[32]; snprintf(w, sizeof w, "  arg[%d]", i);
                describe(w, o, (NSUInteger)(v - g)); hit = YES; break;
            }
        }
        if (!hit) fprintf(gOut, "      arg[%d] = 0x%llx (not a known buffer: texture, sampler or id)\n", i, (unsigned long long)v);
    }
}

// Argument-buffer regions seen at a logged draw. They are checked again when the encoder ends and when the command
// buffer is committed: Metal reads an argument buffer when the GPU runs the draw, so a change in between means the
// draw runs with other resources than it was encoded with.
typedef struct { __unsafe_unretained id<MTLBuffer> buf; NSUInteger off; NSUInteger len; uint64_t hash; int draw; long src; int reported; uint64_t copy[64]; void* enc; unsigned long seq; } Watch;
static Watch gWatch[4096]; static int gNWatch;
static unsigned long gSeq;      // counts encoder calls seen (pipeline and buffer binds, draws)
static void* gCurEnc; static long gCurMesh, gCurObj;
static void addWatch(id<MTLBuffer> b, NSUInteger off, int draw, long src, void* enc) {
    const uint8_t* c = (const uint8_t*)[b contents];
    if (!c || gNWatch >= 4096) return;
    NSUInteger len = (NSUInteger)gArgWords * 8; if (off + len > [b length]) len = [b length] - off;
    if (len > 512) len = 512;
    Watch w = {b, off, len, fnv(c + off, len), draw, src, 0, {0}, enc, gSeq};
    memcpy(w.copy, c + off, len);
    gWatch[gNWatch++] = w;
}
static void checkWatches(const char* when) {
    for (int i = 0; i < gNWatch; i++) {
        Watch* w = &gWatch[i];
        if (w->reported) continue;
        const uint8_t* c = (const uint8_t*)[w->buf contents];
        if (c && fnv(c + w->off, w->len) != w->hash) {
            w->reported = 1;
            fprintf(gOut, "ARGBUF CHANGED %s: argument buffer %p+%lu of draw#%d (meshSrc=%ld) no longer holds what the draw was encoded with; noticed %lu encoder calls later, %s, current pipeline meshSrc=%ld objectSrc=%ld\n",
                    when, (void*)w->buf, (unsigned long)w->off, w->draw, w->src, gSeq - w->seq,
                    gCurEnc == w->enc ? "SAME render pass encoder still open" : "another encoder", gCurMesh, gCurObj);
            for (NSUInteger j = 0; j + 8 <= w->len; j += 8) {
                uint64_t now; memcpy(&now, c + w->off + j, 8);
                uint64_t was = w->copy[j / 8];
                if (now == was) continue;
                fprintf(gOut, "    arg[%lu] was 0x%llx now 0x%llx", (unsigned long)(j / 8), (unsigned long long)was, (unsigned long long)now);
                for (int pass = 0; pass < 2; pass++) {
                    uint64_t v = pass ? now : was;
                    for (id<MTLBuffer> o in gBuffers) { uint64_t g = [o gpuAddress]; if (g && v >= g && v < g + [o length]) { fprintf(gOut, " | %s buffer len=%lu off=%llu", pass ? "now" : "was", (unsigned long)[o length], (unsigned long long)(v - g)); break; } }
                }
                fprintf(gOut, "\n");
            }
        }
    }
}
static void dumpDraw(id enc, const char* kind, NSString* extra) {
    os_unfair_lock_lock(&gLock);
    SpyState* s = stateFor(enc);
    id pipe = s->pipe;
    NSNumber* ml = pipe ? objc_getAssociatedObject(pipe, &kMeshLen) : nil;
    NSNumber* ol = pipe ? objc_getAssociatedObject(pipe, &kObjLen) : nil;
    BOOL want = pipe && (gLens.count == 0 || (ml && [gLens containsObject:ml]));
    if (want) {
        NSNumber* cnt = objc_getAssociatedObject(pipe, &kCount);
        int n = cnt.intValue;
        if (n < gMax) {
            objc_setAssociatedObject(pipe, &kCount, @(n + 1), OBJC_ASSOCIATION_RETAIN);
            fprintf(gOut, "DRAW %s pipeline=%p meshSrc=%ld objectSrc=%ld draw#%d %s\n", kind, (void*)pipe, ml.longValue, ol.longValue, n, extra.UTF8String);
            fprintf(gOut, "  state depthBias=%g slope=%g clamp=%g (%s) viewport=%g,%g %gx%g z %g..%g scissor=%lu,%lu %lux%lu depthClip=%ld cull=%ld winding=%ld fill=%ld stencilRef=%u/%u depthStencilState=%p %s\n",
                    s->bias[0], s->bias[1], s->bias[2], s->biasSet ? "set" : "never set", s->vp.originX, s->vp.originY, s->vp.width, s->vp.height, s->vp.znear, s->vp.zfar,
                    (unsigned long)s->sc.x, (unsigned long)s->sc.y, (unsigned long)s->sc.width, (unsigned long)s->sc.height, s->clip, s->cull, s->winding, s->fill,
                    s->stencilRef[0], s->stencilRef[1], (void*)s->ds, s->ds && [s->ds label] ? [[s->ds label] UTF8String] : "");
            for (int st = 0; st < 2; st++) {
                Slot* t = st ? s->mesh : s->obj;
                fprintf(gOut, "  %s stage\n", st ? "mesh" : "object");
                gUsedNow = s->used;
                for (int i = 0; i < 31; i++) {
                    if (t[i].bytes) { fprintf(gOut, "    [%d] inline bytes len=%lu\n", i, (unsigned long)t[i].blen); continue; }
                    if (!t[i].buf) continue;
                    char w[16]; snprintf(w, sizeof w, "[%d]", i);
                    describe(w, t[i].buf, t[i].off);
                    if (i == 0) decodeArgs(t[i].buf, t[i].off);
                    if (i == 0 && st == 1) addWatch(t[i].buf, t[i].off, n, ml.longValue, (void*)enc);
                }
            }
            gUsedNow = nil;
            fflush(gOut);
        }
    }
    os_unfair_lock_unlock(&gLock);
}

#define SWAP(cls, selname, newimp, orig) do { Method m = class_getInstanceMethod(cls, @selector(selname)); \
    if (m) { orig = (void*)method_getImplementation(m); class_replaceMethod(cls, @selector(selname), (IMP)newimp, method_getTypeEncoding(m)); } \
    else fprintf(gOut, "mtlspy: %s has no %s\n", class_getName(cls), #selname); } while (0)


static void spyTick(id enc, const char* what) {
    gSeq++;
    gCurEnc = (void*)enc;
    if (gNWatch) checkWatches(what);
}
// ---- encoder
static void (*o_setPipe)(id, SEL, id);
static void n_setPipe(id self, SEL _c, id p) { os_unfair_lock_lock(&gLock); stateFor(self)->pipe = p; { NSNumber* a = objc_getAssociatedObject(p, &kMeshLen); NSNumber* b = objc_getAssociatedObject(p, &kObjLen); gCurMesh = a ? a.longValue : 0; gCurObj = b ? b.longValue : 0; } spyTick(self, "at a pipeline bind"); os_unfair_lock_unlock(&gLock); o_setPipe(self, _c, p); }
static void (*o_objBuf)(id, SEL, id, NSUInteger, NSUInteger);
static void n_objBuf(id self, SEL _c, id b, NSUInteger off, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); spyTick(self, "at an object-stage buffer bind"); stateFor(self)->obj[i] = (Slot){b, off, NO, 0}; os_unfair_lock_unlock(&gLock); } o_objBuf(self, _c, b, off, i); }
static void (*o_meshBuf)(id, SEL, id, NSUInteger, NSUInteger);
static void n_meshBuf(id self, SEL _c, id b, NSUInteger off, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); spyTick(self, "at a mesh-stage buffer bind"); stateFor(self)->mesh[i] = (Slot){b, off, NO, 0}; os_unfair_lock_unlock(&gLock); } o_meshBuf(self, _c, b, off, i); }
static void (*o_objOff)(id, SEL, NSUInteger, NSUInteger);
// MTLSPY_FULLBIND=1: an experiment. Turns every offset-only rebind of an object- or mesh-stage buffer into a full
// setObjectBuffer/setMeshBuffer call with the same buffer.
static int gFullBind, gOffCalls[2];
static void n_objOff(id self, SEL _c, NSUInteger off, NSUInteger i) {
    id b = nil;
    if (i < 31) { os_unfair_lock_lock(&gLock); SpyState* s = stateFor(self); s->obj[i].off = off; b = s->obj[i].buf; gOffCalls[0]++; os_unfair_lock_unlock(&gLock); }
    if (gFullBind && b && o_objBuf) { o_objBuf(self, @selector(setObjectBuffer:offset:atIndex:), b, off, i); return; }
    o_objOff(self, _c, off, i);
}
static void (*o_meshOff)(id, SEL, NSUInteger, NSUInteger);
static void n_meshOff(id self, SEL _c, NSUInteger off, NSUInteger i) {
    id b = nil;
    if (i < 31) { os_unfair_lock_lock(&gLock); SpyState* s = stateFor(self); s->mesh[i].off = off; b = s->mesh[i].buf; gOffCalls[1]++; os_unfair_lock_unlock(&gLock); }
    if (gFullBind && b && o_meshBuf) { o_meshBuf(self, @selector(setMeshBuffer:offset:atIndex:), b, off, i); return; }
    o_meshOff(self, _c, off, i);
}
static void (*o_objBytes)(id, SEL, const void*, NSUInteger, NSUInteger);
static void n_objBytes(id self, SEL _c, const void* p, NSUInteger l, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); stateFor(self)->obj[i] = (Slot){nil, 0, YES, l}; os_unfair_lock_unlock(&gLock); } o_objBytes(self, _c, p, l, i); }
static void (*o_meshBytes)(id, SEL, const void*, NSUInteger, NSUInteger);
static void n_meshBytes(id self, SEL _c, const void* p, NSUInteger l, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); stateFor(self)->mesh[i] = (Slot){nil, 0, YES, l}; os_unfair_lock_unlock(&gLock); } o_meshBytes(self, _c, p, l, i); }
static void (*o_use1)(id, SEL, id, NSUInteger, NSUInteger);
static void (*o_draw)(id, SEL, MTLSize, MTLSize, MTLSize);
static void declareArgs(id enc);
static FILE* gState;   // MTLSPY_STATE_OUT
static void stateLine(id enc, const char* kind, long prim);
// MTLSPY_CULL=<0|1|2>: an experiment. Draws of the chosen mesh pipelines run with this MTLCullMode, and the encoder's
// previous cull mode is put back afterwards.
static int gCull = -1;
static void (*o_cull)(id, SEL, NSUInteger);
static BOOL cullOverride(id self, long* prev) {
    if (gCull < 0 || !o_cull) return NO;
    os_unfair_lock_lock(&gLock);
    SpyState* s = stateFor(self);
    NSNumber* ml = s->pipe ? objc_getAssociatedObject(s->pipe, &kMeshLen) : nil;
    BOOL want = ml && [gLens containsObject:ml];
    *prev = s->cull;
    os_unfair_lock_unlock(&gLock);
    if (want) o_cull(self, @selector(setCullMode:), (NSUInteger)gCull);
    return want;
}
static void n_draw(id self, SEL _c, MTLSize g, MTLSize a, MTLSize b) {
    stateLine(self, "mesh", -1);
    declareArgs(self);
    long prevCull = 0;
    if (cullOverride(self, &prevCull)) {
        dumpDraw(self, "groups", @"(cull overridden)");
        o_draw(self, _c, g, a, b);
        o_cull(self, @selector(setCullMode:), (NSUInteger)prevCull);
        return;
    }
    dumpDraw(self, "groups", [NSString stringWithFormat:@"objectGroups=%lux%lux%lu threadsPerObject=%lu threadsPerMesh=%lu", (unsigned long)g.width, (unsigned long)g.height, (unsigned long)g.depth, (unsigned long)a.width, (unsigned long)b.width]);
    o_draw(self, _c, g, a, b);
}
static void (*o_drawInd)(id, SEL, id, NSUInteger, MTLSize, MTLSize);
static void n_drawInd(id self, SEL _c, id ib, NSUInteger off, MTLSize a, MTLSize b) {
    stateLine(self, "meshIndirect", -1);
    const uint32_t* c = (const uint32_t*)((const uint8_t*)[(id<MTLBuffer>)ib contents] + off);
    dumpDraw(self, "indirect", c ? [NSString stringWithFormat:@"indirect=%p+%lu now=%ux%ux%u", (void*)ib, (unsigned long)off, c[0], c[1], c[2]] : @"indirect (private)");
    o_drawInd(self, _c, ib, off, a, b);
}
static void (*o_end)(id, SEL);
static void n_end(id self, SEL _c) { os_unfair_lock_lock(&gLock); gCurEnc = (void*)self; checkWatches("at the end of a render pass"); [gEnc removeObjectForKey:self]; if (gState) fflush(gState); os_unfair_lock_unlock(&gLock); o_end(self, _c); }


// useResource declarations: what an argument buffer points to is only tracked by Metal if it was declared this way
static void noteUse(id enc, id res, NSUInteger usage, NSUInteger stages) {
    if (!res) return;
    SpyState* s = stateFor(enc);
    NSNumber* old = [s->used objectForKey:res];
    NSUInteger v = (old ? old.unsignedLongValue : 0) | (stages & 0xff) | ((usage & MTLResourceUsageWrite) ? 0x100 : 0);
    [s->used setObject:@(v) forKey:res];
}
static void n_use1(id self, SEL _c, id r, NSUInteger u, NSUInteger st) { os_unfair_lock_lock(&gLock); noteUse(self, r, u, st); os_unfair_lock_unlock(&gLock); o_use1(self, _c, r, u, st); }
static void (*o_useN)(id, SEL, const id*, NSUInteger, NSUInteger, NSUInteger);
static void n_useN(id self, SEL _c, const id* r, NSUInteger n, NSUInteger u, NSUInteger st) { os_unfair_lock_lock(&gLock); for (NSUInteger i = 0; i < n; i++) noteUse(self, r[i], u, st); os_unfair_lock_unlock(&gLock); o_useN(self, _c, r, n, u, st); }
static void (*o_use1b)(id, SEL, id, NSUInteger);
static void n_use1b(id self, SEL _c, id r, NSUInteger u) { os_unfair_lock_lock(&gLock); noteUse(self, r, u, 0xff); os_unfair_lock_unlock(&gLock); o_use1b(self, _c, r, u); }
static void (*o_useNb)(id, SEL, const id*, NSUInteger, NSUInteger);
static void n_useNb(id self, SEL _c, const id* r, NSUInteger n, NSUInteger u) { os_unfair_lock_lock(&gLock); for (NSUInteger i = 0; i < n; i++) noteUse(self, r[i], u, 0xff); os_unfair_lock_unlock(&gLock); o_useNb(self, _c, r, n, u); }
static void (*o_useH)(id, SEL, id, NSUInteger);
static void n_useH(id self, SEL _c, id h, NSUInteger st) { os_unfair_lock_lock(&gLock); noteUse(self, h, 0, st); os_unfair_lock_unlock(&gLock); o_useH(self, _c, h, st); }
static void (*o_useHb)(id, SEL, id);
static void n_useHb(id self, SEL _c, id h) { os_unfair_lock_lock(&gLock); noteUse(self, h, 0, 0xff); os_unfair_lock_unlock(&gLock); o_useHb(self, _c, h); }

// MTLSPY_DECLARE=1: an experiment, not a fix. Before each draw of a chosen pipeline, declare every buffer its
// argument buffer (index 0) points to with useResource for the object, mesh and fragment stages.
static int gDeclare = 0;
static void declareArgs(id enc) {
    if (!gDeclare || !o_use1) return;
    os_unfair_lock_lock(&gLock);
    SpyState* s = stateFor(enc);
    id pipe = s->pipe;
    NSNumber* ml = pipe ? objc_getAssociatedObject(pipe, &kMeshLen) : nil;
    id<MTLBuffer> found[80]; int nf = 0;
    if (pipe && (gLens.count == 0 || (ml && [gLens containsObject:ml])) && s->mesh[0].buf) {
        id<MTLBuffer> b = s->mesh[0].buf; NSUInteger off = s->mesh[0].off, len = [b length];
        const uint8_t* c = (const uint8_t*)[b contents];
        for (int i = 0; c && i < gArgWords && off + 8 * (i + 1) <= len && nf < 80; i++) {
            uint64_t v; memcpy(&v, c + off + 8 * i, 8);
            if (!v) continue;
            for (id<MTLBuffer> o in gBuffers) { uint64_t g = [o gpuAddress]; if (g && v >= g && v < g + [o length]) { found[nf++] = o; break; } }
        }
    }
    os_unfair_lock_unlock(&gLock);
    static int said; if (nf && !said) { said = 1; fprintf(gOut, "mtlspy: MTLSPY_DECLARE declares %d buffers per chosen draw\n", nf); }
    for (int i = 0; i < nf; i++) o_use1(enc, @selector(useResource:usage:stages:), found[i], MTLResourceUsageRead | MTLResourceUsageWrite, MTLRenderStageObject | MTLRenderStageMesh | MTLRenderStageFragment);
}

// raster state, kept per encoder and printed with each logged draw
#define LOCKED(stmt) do { os_unfair_lock_lock(&gLock); SpyState* st = stateFor(self); stmt; os_unfair_lock_unlock(&gLock); } while (0)
static void (*o_bias)(id, SEL, float, float, float);
static void n_bias(id self, SEL _c, float b, float sl, float cl) { LOCKED(st->bias[0] = b; st->bias[1] = sl; st->bias[2] = cl; st->biasSet = 1; st->setMask |= 64); o_bias(self, _c, b, sl, cl); }
static void (*o_vp)(id, SEL, MTLViewport);
static void n_vp(id self, SEL _c, MTLViewport v) { LOCKED(st->vp = v; st->vpSet = 1; st->setMask |= 128); o_vp(self, _c, v); }
static void (*o_vps)(id, SEL, const MTLViewport*, NSUInteger);
static void n_vps(id self, SEL _c, const MTLViewport* v, NSUInteger n) { if (n) LOCKED(st->vp = v[0]; st->vpSet = 1; st->setMask |= 128); o_vps(self, _c, v, n); }
static void (*o_sc)(id, SEL, MTLScissorRect);
static void n_sc(id self, SEL _c, MTLScissorRect r) { LOCKED(st->sc = r; st->scSet = 1; st->setMask |= 256); o_sc(self, _c, r); }
static void (*o_scs)(id, SEL, const MTLScissorRect*, NSUInteger);
static void n_scs(id self, SEL _c, const MTLScissorRect* r, NSUInteger n) { if (n) LOCKED(st->sc = r[0]; st->scSet = 1; st->setMask |= 256); o_scs(self, _c, r, n); }
static void (*o_clip)(id, SEL, NSUInteger);
static void n_clip(id self, SEL _c, NSUInteger m) { LOCKED(st->clip = (long)m; st->setMask |= 8); o_clip(self, _c, m); }
static void n_cull(id self, SEL _c, NSUInteger m) { LOCKED(st->cull = (long)m; st->setMask |= 1); o_cull(self, _c, m); }
static void (*o_wind)(id, SEL, NSUInteger);
static void n_wind(id self, SEL _c, NSUInteger m) { LOCKED(st->winding = (long)m; st->setMask |= 2); o_wind(self, _c, m); }
static void (*o_fill)(id, SEL, NSUInteger);
static void n_fill(id self, SEL _c, NSUInteger m) { LOCKED(st->fill = (long)m; st->setMask |= 4); o_fill(self, _c, m); }
static void (*o_sref)(id, SEL, uint32_t);
static void n_sref(id self, SEL _c, uint32_t v) { LOCKED(st->stencilRef[0] = st->stencilRef[1] = v; st->setMask |= 16); o_sref(self, _c, v); }
static void (*o_sref2)(id, SEL, uint32_t, uint32_t);
static void n_sref2(id self, SEL _c, uint32_t f, uint32_t b) { LOCKED(st->stencilRef[0] = f; st->stencilRef[1] = b; st->setMask |= 16); o_sref2(self, _c, f, b); }
static void (*o_ds)(id, SEL, id);
static void n_ds(id self, SEL _c, id d) { LOCKED(st->ds = d; st->setMask |= 32); o_ds(self, _c, d); }
// ---- MTLSPY_STATE_OUT: the state at every draw, tagged with the Vulkan draw it came from
static __thread long tTag = -1;   // the Vulkan draw being encoded on this thread (MoltenVK encodes a command buffer on one thread)
static __thread int tTagSeq;
static void stateLine(id enc, const char* kind, long prim) {
    if (!gState) return;
    os_unfair_lock_lock(&gLock);
    SpyState* s = stateFor(enc);
    fprintf(gState, "M tag=%ld seq=%d enc=%p pipe=%p kind=%s prim=%ld set=0x%x cull=%ld winding=%ld fill=%ld clip=%ld bias=%g,%g,%g vp=%g,%g,%g,%g,%g,%g sc=%lu,%lu,%lu,%lu sref=%u,%u ds=%p rt=%lux%lu\n",
            tTag, tTagSeq++, (void*)enc, (void*)s->pipe, kind, prim, s->setMask, s->cull, s->winding, s->fill, s->clip, s->bias[0], s->bias[1], s->bias[2],
            s->vp.originX, s->vp.originY, s->vp.width, s->vp.height, s->vp.znear, s->vp.zfar,
            (unsigned long)s->sc.x, (unsigned long)s->sc.y, (unsigned long)s->sc.width, (unsigned long)s->sc.height, s->stencilRef[0], s->stencilRef[1], (void*)s->ds, s->rtw, s->rth);
    os_unfair_lock_unlock(&gLock);
}
static void (*o_signpost)(id, SEL, NSString*);
static void n_signpost(id self, SEL _c, NSString* str) {
    const char* c = str.UTF8String;
    if (c && !strncmp(c, "vkspy:d", 7)) { tTag = atol(c + 7); tTagSeq = 0; }
    else if (c && !strcmp(c, "vkspy:x")) tTag = -1;
    o_signpost(self, _c, str);
}
// The draws that are not mesh draws: only their state line is wanted.
#define PLAIN_DRAW(tag, kind, params, args) \
    static void (*o_pd##tag) params; \
    static void n_pd##tag params { stateLine(self, kind, (long)t); o_pd##tag args; }
PLAIN_DRAW(1, "prim", (id self, SEL _c, NSUInteger t, NSUInteger a, NSUInteger b), (self, _c, t, a, b))
PLAIN_DRAW(2, "prim", (id self, SEL _c, NSUInteger t, NSUInteger a, NSUInteger b, NSUInteger i), (self, _c, t, a, b, i))
PLAIN_DRAW(3, "prim", (id self, SEL _c, NSUInteger t, NSUInteger a, NSUInteger b, NSUInteger i, NSUInteger bi), (self, _c, t, a, b, i, bi))
PLAIN_DRAW(4, "indexed", (id self, SEL _c, NSUInteger t, NSUInteger n, NSUInteger it, id ib, NSUInteger o), (self, _c, t, n, it, ib, o))
PLAIN_DRAW(5, "indexed", (id self, SEL _c, NSUInteger t, NSUInteger n, NSUInteger it, id ib, NSUInteger o, NSUInteger i), (self, _c, t, n, it, ib, o, i))
PLAIN_DRAW(6, "indexed", (id self, SEL _c, NSUInteger t, NSUInteger n, NSUInteger it, id ib, NSUInteger o, NSUInteger i, NSInteger bv, NSUInteger bi), (self, _c, t, n, it, ib, o, i, bv, bi))
PLAIN_DRAW(7, "primIndirect", (id self, SEL _c, NSUInteger t, id ib, NSUInteger o), (self, _c, t, ib, o))
PLAIN_DRAW(8, "indexedIndirect", (id self, SEL _c, NSUInteger t, NSUInteger it, id xb, NSUInteger xo, id ib, NSUInteger o), (self, _c, t, it, xb, xo, ib, o))
static void hookEncoder(Class c) {
    static Class done; if (done == c) return; if (done) { fprintf(gOut, "mtlspy: second encoder class %s not hooked\n", class_getName(c)); return; } done = c;
    fprintf(gOut, "mtlspy: encoder class %s\n", class_getName(c));
    SWAP(c, setRenderPipelineState:, n_setPipe, o_setPipe);
    SWAP(c, setObjectBuffer:offset:atIndex:, n_objBuf, o_objBuf);
    SWAP(c, setMeshBuffer:offset:atIndex:, n_meshBuf, o_meshBuf);
    SWAP(c, setObjectBufferOffset:atIndex:, n_objOff, o_objOff);
    SWAP(c, setMeshBufferOffset:atIndex:, n_meshOff, o_meshOff);
    SWAP(c, setObjectBytes:length:atIndex:, n_objBytes, o_objBytes);
    SWAP(c, setMeshBytes:length:atIndex:, n_meshBytes, o_meshBytes);
    SWAP(c, drawMeshThreadgroups:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:, n_draw, o_draw);
    SWAP(c, drawMeshThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:, n_drawInd, o_drawInd);
    SWAP(c, setDepthBias:slopeScale:clamp:, n_bias, o_bias);
    SWAP(c, setViewport:, n_vp, o_vp);
    SWAP(c, setViewports:count:, n_vps, o_vps);
    SWAP(c, setScissorRect:, n_sc, o_sc);
    SWAP(c, setScissorRects:count:, n_scs, o_scs);
    SWAP(c, setDepthClipMode:, n_clip, o_clip);
    SWAP(c, setCullMode:, n_cull, o_cull);
    SWAP(c, setFrontFacingWinding:, n_wind, o_wind);
    SWAP(c, setTriangleFillMode:, n_fill, o_fill);
    SWAP(c, setStencilReferenceValue:, n_sref, o_sref);
    SWAP(c, setStencilFrontReferenceValue:backReferenceValue:, n_sref2, o_sref2);
    SWAP(c, setDepthStencilState:, n_ds, o_ds);
    SWAP(c, useResource:usage:stages:, n_use1, o_use1);
    SWAP(c, useResources:count:usage:stages:, n_useN, o_useN);
    SWAP(c, useResource:usage:, n_use1b, o_use1b);
    SWAP(c, useResources:count:usage:, n_useNb, o_useNb);
    SWAP(c, useHeap:stages:, n_useH, o_useH);
    SWAP(c, useHeap:, n_useHb, o_useHb);
    SWAP(c, endEncoding, n_end, o_end);
    if (gState) {
        SWAP(c, insertDebugSignpost:, n_signpost, o_signpost);
        SWAP(c, drawPrimitives:vertexStart:vertexCount:, n_pd1, o_pd1);
        SWAP(c, drawPrimitives:vertexStart:vertexCount:instanceCount:, n_pd2, o_pd2);
        SWAP(c, drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:, n_pd3, o_pd3);
        SWAP(c, drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:, n_pd4, o_pd4);
        SWAP(c, drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:, n_pd5, o_pd5);
        SWAP(c, drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:baseVertex:baseInstance:, n_pd6, o_pd6);
        SWAP(c, drawPrimitives:indirectBuffer:indirectBufferOffset:, n_pd7, o_pd7);
        SWAP(c, drawIndexedPrimitives:indexType:indexBuffer:indexBufferOffset:indirectBuffer:indirectBufferOffset:, n_pd8, o_pd8);
    }
}
static id (*o_renc)(id, SEL, id);
static id n_renc(id self, SEL _c, id d) {
    id e = o_renc(self, _c, d);
    if (e) {
        MTLRenderPassDescriptor* rp = d;
        id<MTLTexture> t = rp.colorAttachments[0].texture ?: rp.depthAttachment.texture ?: rp.stencilAttachment.texture;
        os_unfair_lock_lock(&gLock);
        hookEncoder(object_getClass(e));
        if (gState) { SpyState* s = stateFor(e); s->rtw = t.width; s->rth = t.height; }
        os_unfair_lock_unlock(&gLock);
    }
    return e;
}

// ---- libraries, functions, pipelines, buffers
static id (*o_func)(id, SEL, NSString*);
static id n_func(id self, SEL _c, NSString* name) { id f = o_func(self, _c, name); if (f) { objc_setAssociatedObject(f, &kLen, objc_getAssociatedObject(self, &kLen), OBJC_ASSOCIATION_RETAIN); } return f; }
static id (*o_lib)(id, SEL, NSString*, id, NSError**);
static void tagLib(id l, NSUInteger len);
static id n_lib(id self, SEL _c, NSString* src, id opt, NSError** err) {
    id l = o_lib(self, _c, src, opt, err);
    if (l) tagLib(l, src.length);
    return l;
}
static id (*o_mpipe)(id, SEL, MTLMeshRenderPipelineDescriptor*, MTLPipelineOption, id*, NSError**);
static id n_mpipe(id self, SEL _c, MTLMeshRenderPipelineDescriptor* d, MTLPipelineOption o, id* refl, NSError** err) {
    id p = o_mpipe(self, _c, d, o, refl, err);
    if (p) {
        NSNumber* ml = d.meshFunction ? objc_getAssociatedObject(d.meshFunction, &kLen) : nil;
        NSNumber* ol = d.objectFunction ? objc_getAssociatedObject(d.objectFunction, &kLen) : nil;
        objc_setAssociatedObject(p, &kMeshLen, ml ?: @(-1), OBJC_ASSOCIATION_RETAIN);
        objc_setAssociatedObject(p, &kObjLen, ol ?: @(-1), OBJC_ASSOCIATION_RETAIN);
        if (gLens.count == 0 || (ml && [gLens containsObject:ml])) {
            os_unfair_lock_lock(&gLock);
            fprintf(gOut, "PIPELINE %p meshSrc=%ld objectSrc=%ld payload=%lu maxGroupsPerMeshGrid=%lu maxThreadsPerObjectGroup=%lu maxThreadsPerMeshGroup=%lu\n", (void*)p, ml.longValue, ol.longValue,
                    (unsigned long)d.payloadMemoryLength, (unsigned long)d.maxTotalThreadgroupsPerMeshGrid, (unsigned long)d.maxTotalThreadsPerObjectThreadgroup, (unsigned long)d.maxTotalThreadsPerMeshThreadgroup);
            fflush(gOut);
            os_unfair_lock_unlock(&gLock);
        }
    }
    return p;
}

// MTLSPY_DUMP_SRC_DIR=dir: write every library source the program compiles to dir/src-<length>.metal
static void dumpSrc(NSString* src) {
    const char* d = getenv("MTLSPY_DUMP_SRC_DIR");
    if (!d) return;
    [src writeToFile:[NSString stringWithFormat:@"%s/src-%lu.metal", d, (unsigned long)src.length] atomically:NO encoding:NSUTF8StringEncoding error:nil];
}
static void tagLib(id l, NSUInteger len) {
    objc_setAssociatedObject(l, &kLen, @(len), OBJC_ASSOCIATION_RETAIN);
    static Class done; Class c = object_getClass(l);
    os_unfair_lock_lock(&gLock);
    if (!done) { done = c; SWAP(c, newFunctionWithName:, n_func, o_func); }
    os_unfair_lock_unlock(&gLock);
}
static void tagPipe(id p, NSNumber* ml, NSNumber* ol, NSUInteger payload, NSUInteger grid, NSUInteger tObj, NSUInteger tMesh) {
    objc_setAssociatedObject(p, &kMeshLen, ml ?: @(-1), OBJC_ASSOCIATION_RETAIN);
    objc_setAssociatedObject(p, &kObjLen, ol ?: @(-1), OBJC_ASSOCIATION_RETAIN);
    if (gLens.count == 0 || (ml && [gLens containsObject:ml])) {
        os_unfair_lock_lock(&gLock);
        fprintf(gOut, "PIPELINE %p meshSrc=%ld objectSrc=%ld payload=%lu maxGroupsPerMeshGrid=%lu maxThreadsPerObjectGroup=%lu maxThreadsPerMeshGroup=%lu\n",
                (void*)p, ml.longValue, ol.longValue, (unsigned long)payload, (unsigned long)grid, (unsigned long)tObj, (unsigned long)tMesh);
        fflush(gOut);
        os_unfair_lock_unlock(&gLock);
    }
}
static void (*o_libA)(id, SEL, NSString*, id, void (^)(id, NSError*));
static void n_libA(id self, SEL _c, NSString* src, id opt, void (^h)(id, NSError*)) {
    NSUInteger len = src.length;
    dumpSrc(src);
    o_libA(self, _c, src, opt, ^(id l, NSError* e) { if (l) tagLib(l, len); h(l, e); });
}
static void (*o_mpipeA)(id, SEL, MTLMeshRenderPipelineDescriptor*, MTLPipelineOption, void (^)(id, id, NSError*));
static void n_mpipeA(id self, SEL _c, MTLMeshRenderPipelineDescriptor* d, MTLPipelineOption o, void (^h)(id, id, NSError*)) {
    NSNumber* ml = d.meshFunction ? objc_getAssociatedObject(d.meshFunction, &kLen) : nil;
    NSNumber* ol = d.objectFunction ? objc_getAssociatedObject(d.objectFunction, &kLen) : nil;
    // MTLSPY_MESH_LIMITS=payloadBytes,groupsPerMeshGrid,threadsPerObjectGroup,threadsPerMeshGroup: an experiment that
    // fills in the mesh pipeline descriptor's limits for pipelines that have an object function (0 leaves one unset).
    if (getenv("MTLSPY_MESH_LIMITS") && d.objectFunction) {
        NSArray<NSString*>* p = [@(getenv("MTLSPY_MESH_LIMITS")) componentsSeparatedByString:@","];
        if (p.count > 0 && p[0].integerValue) d.payloadMemoryLength = p[0].integerValue;
        if (p.count > 1 && p[1].integerValue) d.maxTotalThreadgroupsPerMeshGrid = p[1].integerValue;
        if (p.count > 2 && p[2].integerValue) d.maxTotalThreadsPerObjectThreadgroup = p[2].integerValue;
        if (p.count > 3 && p[3].integerValue) d.maxTotalThreadsPerMeshThreadgroup = p[3].integerValue;
    }
    NSUInteger pl = d.payloadMemoryLength, g = d.maxTotalThreadgroupsPerMeshGrid, a = d.maxTotalThreadsPerObjectThreadgroup, b = d.maxTotalThreadsPerMeshThreadgroup;
    o_mpipeA(self, _c, d, o, ^(id p, id r, NSError* e) { if (p) tagPipe(p, ml, ol, pl, g, a, b); h(p, r, e); });
}
static id (*o_buf)(id, SEL, NSUInteger, MTLResourceOptions);
static id n_buf(id self, SEL _c, NSUInteger len, MTLResourceOptions o) { id b = o_buf(self, _c, len, o); if (b) { os_unfair_lock_lock(&gLock); [gBuffers addObject:b]; os_unfair_lock_unlock(&gLock); } return b; }
static id (*o_bufB)(id, SEL, const void*, NSUInteger, MTLResourceOptions);
static id n_bufB(id self, SEL _c, const void* p, NSUInteger len, MTLResourceOptions o) { id b = o_bufB(self, _c, p, len, o); if (b) { os_unfair_lock_lock(&gLock); [gBuffers addObject:b]; os_unfair_lock_unlock(&gLock); } return b; }
static id (*o_hbuf)(id, SEL, NSUInteger, MTLResourceOptions);
static id n_hbuf(id self, SEL _c, NSUInteger len, MTLResourceOptions o) { id b = o_hbuf(self, _c, len, o); if (b) { os_unfair_lock_lock(&gLock); [gBuffers addObject:b]; os_unfair_lock_unlock(&gLock); } return b; }
static id (*o_hbufO)(id, SEL, NSUInteger, MTLResourceOptions, NSUInteger);
static id n_hbufO(id self, SEL _c, NSUInteger len, MTLResourceOptions o, NSUInteger off) { id b = o_hbufO(self, _c, len, o, off); if (b) { os_unfair_lock_lock(&gLock); [gBuffers addObject:b]; os_unfair_lock_unlock(&gLock); } return b; }
static id (*o_heap)(id, SEL, id);
static id n_heap(id self, SEL _c, id d) {
    id h = o_heap(self, _c, d);
    if (h) { static Class done; Class c = object_getClass(h); os_unfair_lock_lock(&gLock);
        if (!done) { done = c; SWAP(c, newBufferWithLength:options:, n_hbuf, o_hbuf); SWAP(c, newBufferWithLength:options:offset:, n_hbufO, o_hbufO); }
        os_unfair_lock_unlock(&gLock); }
    return h;
}


// ---- compute (an emulated mesh program runs as a compute kernel; its inputs can be compared with the native draw's)
@interface SpyCState : NSObject { @public Slot buf[31]; __unsafe_unretained id pipe; } @end
@implementation SpyCState @end
static NSMapTable* gCEnc;
static SpyCState* cstateFor(id enc) { SpyCState* s = [gCEnc objectForKey:enc]; if (!s) { s = [SpyCState new]; [gCEnc setObject:s forKey:enc]; } return s; }
static void dumpDispatch(id enc, NSString* extra) {
    os_unfair_lock_lock(&gLock);
    SpyCState* s = cstateFor(enc);
    id pipe = s->pipe;
    NSNumber* ml = pipe ? objc_getAssociatedObject(pipe, &kMeshLen) : nil;
    if (pipe && ml && [gLens containsObject:ml]) {
        int n = [objc_getAssociatedObject(pipe, &kCount) intValue];
        if (n < gMax) {
            objc_setAssociatedObject(pipe, &kCount, @(n + 1), OBJC_ASSOCIATION_RETAIN);
            fprintf(gOut, "DISPATCH pipeline=%p computeSrc=%ld dispatch#%d %s\n  compute stage\n", (void*)pipe, ml.longValue, n, extra.UTF8String);
            for (int i = 0; i < 31; i++) {
                if (!s->buf[i].buf) continue;
                char w[16]; snprintf(w, sizeof w, "[%d]", i);
                describe(w, s->buf[i].buf, s->buf[i].off);
                if (i == 0) decodeArgs(s->buf[i].buf, s->buf[i].off);
            }
            fflush(gOut);
        }
    }
    os_unfair_lock_unlock(&gLock);
}
static void (*o_csetPipe)(id, SEL, id);
static void n_csetPipe(id self, SEL _c, id p) { os_unfair_lock_lock(&gLock); cstateFor(self)->pipe = p; os_unfair_lock_unlock(&gLock); o_csetPipe(self, _c, p); }
static void (*o_cBuf)(id, SEL, id, NSUInteger, NSUInteger);
static void n_cBuf(id self, SEL _c, id b, NSUInteger off, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); cstateFor(self)->buf[i] = (Slot){b, off, NO, 0}; os_unfair_lock_unlock(&gLock); } o_cBuf(self, _c, b, off, i); }
static void (*o_cOff)(id, SEL, NSUInteger, NSUInteger);
static void n_cOff(id self, SEL _c, NSUInteger off, NSUInteger i) { if (i < 31) { os_unfair_lock_lock(&gLock); cstateFor(self)->buf[i].off = off; os_unfair_lock_unlock(&gLock); } o_cOff(self, _c, off, i); }
static void (*o_cDisp)(id, SEL, MTLSize, MTLSize);
static void n_cDisp(id self, SEL _c, MTLSize g, MTLSize t) { dumpDispatch(self, [NSString stringWithFormat:@"groups=%lux%lux%lu threads=%lu", (unsigned long)g.width, (unsigned long)g.height, (unsigned long)g.depth, (unsigned long)t.width]); o_cDisp(self, _c, g, t); }
static void (*o_cDispInd)(id, SEL, id, NSUInteger, MTLSize);
static void n_cDispInd(id self, SEL _c, id ib, NSUInteger off, MTLSize t) { dumpDispatch(self, @"indirect"); o_cDispInd(self, _c, ib, off, t); }
static void (*o_cEnd)(id, SEL);
static void n_cEnd(id self, SEL _c) { os_unfair_lock_lock(&gLock); [gCEnc removeObjectForKey:self]; os_unfair_lock_unlock(&gLock); o_cEnd(self, _c); }
static void hookCEncoder(Class c) {
    static Class done; if (done) return; done = c;
    fprintf(gOut, "mtlspy: compute encoder class %s\n", class_getName(c));
    SWAP(c, setComputePipelineState:, n_csetPipe, o_csetPipe);
    SWAP(c, setBuffer:offset:atIndex:, n_cBuf, o_cBuf);
    SWAP(c, setBufferOffset:atIndex:, n_cOff, o_cOff);
    SWAP(c, dispatchThreadgroups:threadsPerThreadgroup:, n_cDisp, o_cDisp);
    SWAP(c, dispatchThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerThreadgroup:, n_cDispInd, o_cDispInd);
    SWAP(c, endEncoding, n_cEnd, o_cEnd);
}
static id (*o_cenc1)(id, SEL, MTLDispatchType);
static id n_cenc1(id self, SEL _c, MTLDispatchType t) { id e = o_cenc1(self, _c, t); if (e) { os_unfair_lock_lock(&gLock); hookCEncoder(object_getClass(e)); os_unfair_lock_unlock(&gLock); } return e; }
static id (*o_cenc2)(id, SEL, id);
static id n_cenc2(id self, SEL _c, id d) { id e = o_cenc2(self, _c, d); if (e) { os_unfair_lock_lock(&gLock); hookCEncoder(object_getClass(e)); os_unfair_lock_unlock(&gLock); } return e; }
static void (*o_cpipeA)(id, SEL, MTLComputePipelineDescriptor*, MTLPipelineOption, void (^)(id, id, NSError*));
static void n_cpipeA(id self, SEL _c, MTLComputePipelineDescriptor* d, MTLPipelineOption o, void (^h)(id, id, NSError*)) {
    NSNumber* ml = d.computeFunction ? objc_getAssociatedObject(d.computeFunction, &kLen) : nil;
    o_cpipeA(self, _c, d, o, ^(id p, id r, NSError* e) {
        if (p) {
            objc_setAssociatedObject(p, &kMeshLen, ml ?: @(-1), OBJC_ASSOCIATION_RETAIN);
            if (gListCompute || (ml && [gLens containsObject:ml])) { os_unfair_lock_lock(&gLock); fprintf(gOut, "COMPUTE PIPELINE %p computeSrc=%ld\n", (void*)p, ml.longValue); fflush(gOut); os_unfair_lock_unlock(&gLock); }
        }
        h(p, r, e); });
}

static void (*o_commit)(id, SEL);
static void n_commit(id self, SEL _c) { os_unfair_lock_lock(&gLock); { static int said; if (!said && gOffCalls[0] + gOffCalls[1] > 200) { said = 1; fprintf(gOut, "mtlspy: offset-only rebinds so far: object %d, mesh %d (MTLSPY_FULLBIND=%d)\n", gOffCalls[0], gOffCalls[1], gFullBind); fflush(gOut); } } gCurEnc = NULL; checkWatches("at a command buffer commit"); int k = 0; for (int i = 0; i < gNWatch; i++) if (!gWatch[i].reported && k < 4096) gWatch[k++] = gWatch[i]; if (gNWatch > 3000) gNWatch = 0; os_unfair_lock_unlock(&gLock); o_commit(self, _c); }
__attribute__((constructor)) static void spyInit(void) {
    const char* out = getenv("MTLSPY_OUT");
    gOut = out ? fopen(out, "w") : stderr; if (!gOut) gOut = stderr;
    gLens = [NSMutableSet new];
    const char* lens = getenv("MTLSPY_SRC_LENS");
    if (lens) for (NSString* p in [@(lens) componentsSeparatedByString:@","]) if (p.length) [gLens addObject:@(p.longLongValue)];
    if (getenv("MTLSPY_HASH")) { gNWin = 0; for (NSString* p in [@(getenv("MTLSPY_HASH")) componentsSeparatedByString:@","]) if (p.length && gNWin < 8) gWin[gNWin++] = (size_t)p.longLongValue; }
    gListCompute = getenv("MTLSPY_LIST_COMPUTE") != NULL;
    gCEnc = [[NSMapTable mapTableWithKeyOptions:NSPointerFunctionsOpaqueMemory | NSPointerFunctionsOpaquePersonality valueOptions:NSPointerFunctionsStrongMemory] retain];
    gDeclare = getenv("MTLSPY_DECLARE") != NULL;
    if (getenv("MTLSPY_CULL")) gCull = atoi(getenv("MTLSPY_CULL"));
    gFullBind = getenv("MTLSPY_FULLBIND") != NULL;
    if (getenv("MTLSPY_HEX")) gHex = atoi(getenv("MTLSPY_HEX"));
    if (getenv("MTLSPY_MAX")) gMax = atoi(getenv("MTLSPY_MAX"));
    if (getenv("MTLSPY_ARG_WORDS")) gArgWords = atoi(getenv("MTLSPY_ARG_WORDS"));
    if (getenv("MTLSPY_STATE_OUT")) { gState = fopen(getenv("MTLSPY_STATE_OUT"), "w"); if (!gState) fprintf(gOut, "mtlspy: cannot write MTLSPY_STATE_OUT=%s\n", getenv("MTLSPY_STATE_OUT")); }
    gBuffers = [[NSHashTable weakObjectsHashTable] retain];
    gEnc = [[NSMapTable mapTableWithKeyOptions:NSPointerFunctionsOpaqueMemory | NSPointerFunctionsOpaquePersonality valueOptions:NSPointerFunctionsStrongMemory] retain];
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    if (!dev) { fprintf(gOut, "mtlspy: no Metal device\n"); return; }
    Class dc = object_getClass(dev);
    SWAP(dc, newLibraryWithSource:options:error:, n_lib, o_lib);
    SWAP(dc, newRenderPipelineStateWithMeshDescriptor:options:reflection:error:, n_mpipe, o_mpipe);
    SWAP(dc, newLibraryWithSource:options:completionHandler:, n_libA, o_libA);
    SWAP(dc, newRenderPipelineStateWithMeshDescriptor:options:completionHandler:, n_mpipeA, o_mpipeA);
    SWAP(dc, newBufferWithLength:options:, n_buf, o_buf);
    SWAP(dc, newBufferWithBytes:length:options:, n_bufB, o_bufB);
    SWAP(dc, newHeapWithDescriptor:, n_heap, o_heap);
    id<MTLCommandQueue> q = [dev newCommandQueue];
    Class cc = object_getClass([q commandBuffer]);
    SWAP(cc, renderCommandEncoderWithDescriptor:, n_renc, o_renc);
    SWAP(cc, commit, n_commit, o_commit);
    SWAP(cc, computeCommandEncoderWithDispatchType:, n_cenc1, o_cenc1);
    SWAP(cc, computeCommandEncoderWithDescriptor:, n_cenc2, o_cenc2);
    SWAP(dc, newComputePipelineStateWithDescriptor:options:completionHandler:, n_cpipeA, o_cpipeA);
    fprintf(gOut, "mtlspy: device %s, command buffer class %s\n", class_getName(dc), class_getName(cc));
    fflush(gOut);
}
