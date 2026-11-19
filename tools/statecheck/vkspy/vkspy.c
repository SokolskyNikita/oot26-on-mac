// vkspy: a Vulkan library that sits in front of the real one (MoltenVK) and records what the program REQUESTED for
// every draw: the raw pipeline create info and the raw dynamic state, exactly as passed in. It forwards every call
// unchanged. It is the requested half of the Vulkan-to-Metal state check; mtlspy records the half Metal was given.
//
// It reads nothing from MoltenVK, so a fault in MoltenVK's own view of a pipeline cannot hide in this log.
//
// Before each draw it inserts a debug label "vkspy:d<id>" and after it "vkspy:x". MoltenVK turns a label into
// insertDebugSignpost: on the Metal encoder, where mtlspy reads the id back, so both logs name the same draw.
//
//   VKSPY_REAL=path   the real Vulkan library (required)
//   VKSPY_OUT=file    log file (default stderr)
//   VKSPY_NOLABEL=1   record only, insert no labels (to check the labels change nothing)
//
// Use: point the program's Vulkan library path at libvkspy.dylib (Lichii: LIBVULKAN_PATH).
//
// Log lines, one per event, key=value:
//   F  a framebuffer: size
//   P  a graphics pipeline: stages, mesh output topology, the static state, the list of dynamic states
//   R  a render pass begin: command buffer, framebuffer, render area
//   D  a draw: id, command buffer, bound pipeline, and the dynamic state current in that command buffer. `set` has
//      one bit per dynamic value that a vkCmdSet* call has set since vkBeginCommandBuffer (bits: see SET_* below);
//      a value whose bit is clear was never set and prints as 0.
// Enum values are Vulkan's own numbers.
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { SET_VIEWPORT = 1, SET_SCISSOR = 2, SET_BIAS = 4, SET_CULL = 8, SET_FRONT = 16, SET_TOPO = 32, SET_BIAS_EN = 64,
       SET_CLAMP_EN = 128, SET_DISCARD = 256, SET_DTEST = 512, SET_DWRITE = 1024, SET_DCMP = 2048, SET_STEST = 4096,
       SET_SREF_FRONT = 8192, SET_SREF_BACK = 16384 };

typedef struct {
    uint64_t pipe, fb;
    uint32_t set;
    VkViewport vp; uint32_t vpCount;
    VkRect2D sc; uint32_t scCount;
    float bias[3];   // constant, clamp, slope
    uint32_t cull, front, topo, biasEn, clampEn, discard, dtest, dwrite, dcmp, stest, sref[2];
} Cb;

// ---- a small map from a handle to a pointer or a number (entries are replaced, never removed)
#define MAP_BITS 18
typedef struct { uint64_t key[1 << MAP_BITS]; void* val[1 << MAP_BITS]; } Map;
static Map gCbs, gModules;
static void** mapSlot(Map* m, uint64_t k) {
    uint64_t i = (k * 0x9E3779B97F4A7C15ull) >> (64 - MAP_BITS);
    for (uint32_t n = 0; n < (1u << MAP_BITS); n++, i = (i + 1) & ((1u << MAP_BITS) - 1)) {
        if (m->key[i] == k) return &m->val[i];
        if (!m->key[i]) { m->key[i] = k; return &m->val[i]; }
    }
    return NULL;
}

static FILE* gOut;
static pthread_mutex_t gLock = PTHREAD_MUTEX_INITIALIZER;
static void* gReal;
static int gNoLabel;
static uint64_t gDrawId;
static PFN_vkGetInstanceProcAddr r_gipa;
static PFN_vkGetDeviceProcAddr r_gdpa;
static PFN_vkCmdInsertDebugUtilsLabelEXT r_label;

static void init(void) {
    static int done; if (done) return; done = 1;
    const char* out = getenv("VKSPY_OUT");
    gOut = out ? fopen(out, "w") : stderr; if (!gOut) gOut = stderr;
    const char* real = getenv("VKSPY_REAL");
    gReal = real ? dlopen(real, RTLD_NOW | RTLD_LOCAL) : NULL;
    if (!gReal) { fprintf(gOut, "vkspy: cannot open VKSPY_REAL=%s: %s\n", real ? real : "(unset)", dlerror()); fflush(gOut); return; }
    r_gipa = (PFN_vkGetInstanceProcAddr)dlsym(gReal, "vkGetInstanceProcAddr");
    r_gdpa = (PFN_vkGetDeviceProcAddr)dlsym(gReal, "vkGetDeviceProcAddr");
    gNoLabel = getenv("VKSPY_NOLABEL") != NULL;
    // Taken by symbol, not through vkGetDeviceProcAddr, which hides the function when VK_EXT_debug_utils is not enabled.
    if (!gNoLabel) r_label = (PFN_vkCmdInsertDebugUtilsLabelEXT)dlsym(gReal, "vkCmdInsertDebugUtilsLabelEXT");
    fprintf(gOut, "vkspy: real=%s labels=%s\n", real, gNoLabel ? "off (VKSPY_NOLABEL)" : r_label ? "on" : "OFF: the real library exports no vkCmdInsertDebugUtilsLabelEXT, draws are not tagged");
    fflush(gOut);
}

static Cb* cbOf(VkCommandBuffer c) {
    void** s = mapSlot(&gCbs, (uint64_t)(uintptr_t)c);
    if (!s) return NULL;
    if (!*s) *s = calloc(1, sizeof(Cb));
    return (Cb*)*s;
}
#define WITH_CB(c, stmt) do { pthread_mutex_lock(&gLock); Cb* cb = cbOf(c); if (cb) { stmt; } pthread_mutex_unlock(&gLock); } while (0)

// The output primitive a mesh shader declares (OpExecutionMode OutputPoints / OutputLinesEXT / OutputTrianglesEXT)
// as a VkPrimitiveTopology, or -1.
static int meshOutput(const uint32_t* code, size_t words) {
    for (size_t w = 5; code && w < words; ) {
        uint32_t op = code[w] & 0xffff, len = code[w] >> 16;
        if (!len || op == 54 /* OpFunction */) break;
        if (op == 16 /* OpExecutionMode */ && len >= 3 && w + 2 < words) {
            switch (code[w + 2]) {
                case 27: return VK_PRIMITIVE_TOPOLOGY_POINT_LIST;
                case 5269: return VK_PRIMITIVE_TOPOLOGY_LINE_LIST;
                case 5298: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
                default: break;
            }
        }
        w += len;
    }
    return -1;
}

// ---- wrapped calls
static PFN_vkCreateShaderModule r_CreateShaderModule;
static VkResult VKAPI_CALL w_CreateShaderModule(VkDevice d, const VkShaderModuleCreateInfo* ci, const VkAllocationCallbacks* a, VkShaderModule* m) {
    VkResult r = r_CreateShaderModule(d, ci, a, m);
    if (r == VK_SUCCESS && ci && m) {
        int out = meshOutput(ci->pCode, ci->codeSize / 4);
        pthread_mutex_lock(&gLock);
        void** s = mapSlot(&gModules, (uint64_t)*m);
        if (s) *s = (void*)(intptr_t)(out + 2);   // 0 = unknown module, 1 = no mesh output, 2.. = topology + 2
        pthread_mutex_unlock(&gLock);
    }
    return r;
}

static PFN_vkCreateFramebuffer r_CreateFramebuffer;
static VkResult VKAPI_CALL w_CreateFramebuffer(VkDevice d, const VkFramebufferCreateInfo* ci, const VkAllocationCallbacks* a, VkFramebuffer* f) {
    VkResult r = r_CreateFramebuffer(d, ci, a, f);
    if (r == VK_SUCCESS && ci && f) {
        pthread_mutex_lock(&gLock);
        fprintf(gOut, "F fb=0x%llx w=%u h=%u layers=%u attachments=%u\n", (unsigned long long)*f, ci->width, ci->height, ci->layers, ci->attachmentCount);
        pthread_mutex_unlock(&gLock);
    }
    return r;
}

static void logPipeline(const VkGraphicsPipelineCreateInfo* ci, VkPipeline p) {
    uint32_t stages = 0; int meshOut = -1;
    for (uint32_t i = 0; i < ci->stageCount; i++) {
        const VkPipelineShaderStageCreateInfo* ss = &ci->pStages[i];
        stages |= ss->stage;
        if (ss->stage != VK_SHADER_STAGE_MESH_BIT_EXT) continue;
        if (ss->module) {
            void** s = mapSlot(&gModules, (uint64_t)ss->module);
            if (s && *s) meshOut = (int)(intptr_t)*s - 2;
        } else {
            for (const VkBaseInStructure* n = (const VkBaseInStructure*)ss->pNext; n; n = n->pNext)
                if (n->sType == VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO) {
                    const VkShaderModuleCreateInfo* sm = (const VkShaderModuleCreateInfo*)n;
                    meshOut = meshOutput(sm->pCode, sm->codeSize / 4);
                }
        }
    }
    fprintf(gOut, "P pipe=0x%llx stages=0x%x meshOut=%d rp=0x%llx subpass=%u", (unsigned long long)p, stages, meshOut, (unsigned long long)ci->renderPass, ci->subpass);
    int dynViewport = 0, dynScissor = 0;
    fprintf(gOut, " dyn=");
    if (ci->pDynamicState)
        for (uint32_t i = 0; i < ci->pDynamicState->dynamicStateCount; i++) {
            VkDynamicState s = ci->pDynamicState->pDynamicStates[i];
            if (s == VK_DYNAMIC_STATE_VIEWPORT) dynViewport = 1;
            if (s == VK_DYNAMIC_STATE_SCISSOR) dynScissor = 1;
            fprintf(gOut, "%s%d", i ? "," : "", (int)s);
        }
    if (ci->pInputAssemblyState) fprintf(gOut, " ia=1 topo=%d restart=%u", (int)ci->pInputAssemblyState->topology, ci->pInputAssemblyState->primitiveRestartEnable);
    else fprintf(gOut, " ia=0");
    const VkPipelineRasterizationStateCreateInfo* rs = ci->pRasterizationState;
    if (rs) {
        int clipEn = -1;   // -1: no VkPipelineRasterizationDepthClipStateCreateInfoEXT, so depth clip = !depthClampEnable
        for (const VkBaseInStructure* n = (const VkBaseInStructure*)rs->pNext; n; n = n->pNext)
            if (n->sType == VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_DEPTH_CLIP_STATE_CREATE_INFO_EXT)
                clipEn = ((const VkPipelineRasterizationDepthClipStateCreateInfoEXT*)n)->depthClipEnable;
        fprintf(gOut, " rs=1 clampEn=%u discard=%u poly=%d cull=%u front=%d biasEn=%u bias=%g,%g,%g lineWidth=%g clipEn=%d",
                rs->depthClampEnable, rs->rasterizerDiscardEnable, (int)rs->polygonMode, rs->cullMode, (int)rs->frontFace, rs->depthBiasEnable,
                rs->depthBiasConstantFactor, rs->depthBiasClamp, rs->depthBiasSlopeFactor, rs->lineWidth, clipEn);
    } else fprintf(gOut, " rs=0");
    const VkPipelineViewportStateCreateInfo* vs = ci->pViewportState;
    if (vs) {
        int negOne = -1;   // -1: no VkPipelineViewportDepthClipControlCreateInfoEXT
        for (const VkBaseInStructure* n = (const VkBaseInStructure*)vs->pNext; n; n = n->pNext)
            if (n->sType == VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_DEPTH_CLIP_CONTROL_CREATE_INFO_EXT)
                negOne = ((const VkPipelineViewportDepthClipControlCreateInfoEXT*)n)->negativeOneToOne;
        fprintf(gOut, " vs=1 vpCount=%u scCount=%u negOneToOne=%d", vs->viewportCount, vs->scissorCount, negOne);
        if (!dynViewport && vs->pViewports && vs->viewportCount) { const VkViewport* v = vs->pViewports; fprintf(gOut, " vp=%g,%g,%g,%g,%g,%g", v->x, v->y, v->width, v->height, v->minDepth, v->maxDepth); }
        if (!dynScissor && vs->pScissors && vs->scissorCount) { const VkRect2D* s = vs->pScissors; fprintf(gOut, " sc=%d,%d,%u,%u", s->offset.x, s->offset.y, s->extent.width, s->extent.height); }
    } else fprintf(gOut, " vs=0");
    const VkPipelineDepthStencilStateCreateInfo* ds = ci->pDepthStencilState;
    if (ds) fprintf(gOut, " ds=1 dtest=%u dwrite=%u dcmp=%d stest=%u sref=%u,%u", ds->depthTestEnable, ds->depthWriteEnable, (int)ds->depthCompareOp, ds->stencilTestEnable, ds->front.reference, ds->back.reference);
    else fprintf(gOut, " ds=0");
    fprintf(gOut, "\n");
}

static PFN_vkCreateGraphicsPipelines r_CreateGraphicsPipelines;
static VkResult VKAPI_CALL w_CreateGraphicsPipelines(VkDevice d, VkPipelineCache c, uint32_t n, const VkGraphicsPipelineCreateInfo* ci, const VkAllocationCallbacks* a, VkPipeline* p) {
    VkResult r = r_CreateGraphicsPipelines(d, c, n, ci, a, p);
    if (ci && p) {
        pthread_mutex_lock(&gLock);
        for (uint32_t i = 0; i < n; i++) if (p[i]) logPipeline(&ci[i], p[i]);
        pthread_mutex_unlock(&gLock);
    }
    return r;
}

static PFN_vkBeginCommandBuffer r_BeginCommandBuffer;
static VkResult VKAPI_CALL w_BeginCommandBuffer(VkCommandBuffer c, const VkCommandBufferBeginInfo* bi) {
    WITH_CB(c, memset(cb, 0, sizeof *cb); fflush(gOut));
    return r_BeginCommandBuffer(c, bi);
}

static PFN_vkCmdBindPipeline r_CmdBindPipeline;
static void VKAPI_CALL w_CmdBindPipeline(VkCommandBuffer c, VkPipelineBindPoint bp, VkPipeline p) {
    if (bp == VK_PIPELINE_BIND_POINT_GRAPHICS) WITH_CB(c, cb->pipe = (uint64_t)p);
    r_CmdBindPipeline(c, bp, p);
}

static PFN_vkCmdBeginRenderPass r_CmdBeginRenderPass;
static void VKAPI_CALL w_CmdBeginRenderPass(VkCommandBuffer c, const VkRenderPassBeginInfo* bi, VkSubpassContents sc) {
    WITH_CB(c, cb->fb = (uint64_t)bi->framebuffer;
            fprintf(gOut, "R cb=%p rp=0x%llx fb=0x%llx area=%d,%d,%u,%u\n", (void*)c, (unsigned long long)bi->renderPass, (unsigned long long)bi->framebuffer,
                    bi->renderArea.offset.x, bi->renderArea.offset.y, bi->renderArea.extent.width, bi->renderArea.extent.height));
    r_CmdBeginRenderPass(c, bi, sc);
}

static PFN_vkCmdSetViewport r_CmdSetViewport;
static void VKAPI_CALL w_CmdSetViewport(VkCommandBuffer c, uint32_t first, uint32_t n, const VkViewport* v) {
    if (first == 0 && n) WITH_CB(c, cb->vp = v[0]; cb->vpCount = n; cb->set |= SET_VIEWPORT);
    r_CmdSetViewport(c, first, n, v);
}
static PFN_vkCmdSetScissor r_CmdSetScissor;
static void VKAPI_CALL w_CmdSetScissor(VkCommandBuffer c, uint32_t first, uint32_t n, const VkRect2D* s) {
    if (first == 0 && n) WITH_CB(c, cb->sc = s[0]; cb->scCount = n; cb->set |= SET_SCISSOR);
    r_CmdSetScissor(c, first, n, s);
}
static PFN_vkCmdSetDepthBias r_CmdSetDepthBias;
static void VKAPI_CALL w_CmdSetDepthBias(VkCommandBuffer c, float constant, float clamp, float slope) {
    WITH_CB(c, cb->bias[0] = constant; cb->bias[1] = clamp; cb->bias[2] = slope; cb->set |= SET_BIAS);
    r_CmdSetDepthBias(c, constant, clamp, slope);
}
static PFN_vkCmdSetDepthBias2EXT r_CmdSetDepthBias2EXT;
static void VKAPI_CALL w_CmdSetDepthBias2EXT(VkCommandBuffer c, const VkDepthBiasInfoEXT* i) {
    WITH_CB(c, cb->bias[0] = i->depthBiasConstantFactor; cb->bias[1] = i->depthBiasClamp; cb->bias[2] = i->depthBiasSlopeFactor; cb->set |= SET_BIAS);
    r_CmdSetDepthBias2EXT(c, i);
}
static PFN_vkCmdSetStencilReference r_CmdSetStencilReference;
static void VKAPI_CALL w_CmdSetStencilReference(VkCommandBuffer c, VkStencilFaceFlags faces, uint32_t ref) {
    WITH_CB(c, if (faces & VK_STENCIL_FACE_FRONT_BIT) { cb->sref[0] = ref; cb->set |= SET_SREF_FRONT; }
               if (faces & VK_STENCIL_FACE_BACK_BIT) { cb->sref[1] = ref; cb->set |= SET_SREF_BACK; });
    r_CmdSetStencilReference(c, faces, ref);
}
// One-value dynamic state: vkCmdSet<Name>(commandBuffer, value).
#define SET1(Name, T, field, bit) \
    static void (VKAPI_CALL *r_CmdSet##Name)(VkCommandBuffer, T); \
    static void VKAPI_CALL w_CmdSet##Name(VkCommandBuffer c, T v) { WITH_CB(c, cb->field = (uint32_t)v; cb->set |= bit); r_CmdSet##Name(c, v); }
SET1(CullMode, VkCullModeFlags, cull, SET_CULL)
SET1(FrontFace, VkFrontFace, front, SET_FRONT)
SET1(PrimitiveTopology, VkPrimitiveTopology, topo, SET_TOPO)
SET1(DepthBiasEnable, VkBool32, biasEn, SET_BIAS_EN)
SET1(DepthClampEnable, VkBool32, clampEn, SET_CLAMP_EN)
SET1(RasterizerDiscardEnable, VkBool32, discard, SET_DISCARD)
SET1(DepthTestEnable, VkBool32, dtest, SET_DTEST)
SET1(DepthWriteEnable, VkBool32, dwrite, SET_DWRITE)
SET1(DepthCompareOp, VkCompareOp, dcmp, SET_DCMP)
SET1(StencilTestEnable, VkBool32, stest, SET_STEST)

// ---- draws
static void label(VkCommandBuffer c, const char* name) {
    if (!r_label) return;
    VkDebugUtilsLabelEXT l = { VK_STRUCTURE_TYPE_DEBUG_UTILS_LABEL_EXT, NULL, name, {0, 0, 0, 0} };
    r_label(c, &l);
}
static void preDraw(VkCommandBuffer c, const char* kind) {
    char name[40];
    pthread_mutex_lock(&gLock);
    uint64_t id = ++gDrawId;
    Cb* cb = cbOf(c);
    if (cb)
        fprintf(gOut, "D id=%llu cb=%p pipe=0x%llx kind=%s fb=0x%llx set=0x%x vp=%g,%g,%g,%g,%g,%g vpCount=%u sc=%d,%d,%u,%u bias=%g,%g,%g cull=%u front=%u topo=%u biasEn=%u clampEn=%u discard=%u dtest=%u dwrite=%u dcmp=%u stest=%u sref=%u,%u\n",
                (unsigned long long)id, (void*)c, (unsigned long long)cb->pipe, kind, (unsigned long long)cb->fb, cb->set,
                cb->vp.x, cb->vp.y, cb->vp.width, cb->vp.height, cb->vp.minDepth, cb->vp.maxDepth, cb->vpCount,
                cb->sc.offset.x, cb->sc.offset.y, cb->sc.extent.width, cb->sc.extent.height, cb->bias[0], cb->bias[1], cb->bias[2],
                cb->cull, cb->front, cb->topo, cb->biasEn, cb->clampEn, cb->discard, cb->dtest, cb->dwrite, cb->dcmp, cb->stest, cb->sref[0], cb->sref[1]);
    pthread_mutex_unlock(&gLock);
    snprintf(name, sizeof name, "vkspy:d%llu", (unsigned long long)id);
    label(c, name);
}
#define DRAW(Name, kind, params, args) \
    static void (VKAPI_CALL *r_Cmd##Name) params; \
    static void VKAPI_CALL w_Cmd##Name params { preDraw(c, kind); r_Cmd##Name args; label(c, "vkspy:x"); }
DRAW(Draw, "draw", (VkCommandBuffer c, uint32_t a, uint32_t b, uint32_t d, uint32_t e), (c, a, b, d, e))
DRAW(DrawIndexed, "indexed", (VkCommandBuffer c, uint32_t a, uint32_t b, uint32_t d, int32_t e, uint32_t f), (c, a, b, d, e, f))
DRAW(DrawIndirect, "indirect", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, uint32_t n, uint32_t s), (c, b, o, n, s))
DRAW(DrawIndexedIndirect, "indexedIndirect", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, uint32_t n, uint32_t s), (c, b, o, n, s))
DRAW(DrawIndirectCount, "indirectCount", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, VkBuffer cb2, VkDeviceSize co, uint32_t n, uint32_t s), (c, b, o, cb2, co, n, s))
DRAW(DrawIndexedIndirectCount, "indexedIndirectCount", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, VkBuffer cb2, VkDeviceSize co, uint32_t n, uint32_t s), (c, b, o, cb2, co, n, s))
DRAW(DrawIndirectByteCountEXT, "byteCount", (VkCommandBuffer c, uint32_t a, uint32_t b, VkBuffer cb2, VkDeviceSize o, uint32_t d, uint32_t e), (c, a, b, cb2, o, d, e))
DRAW(DrawMeshTasksEXT, "mesh", (VkCommandBuffer c, uint32_t x, uint32_t y, uint32_t z), (c, x, y, z))
DRAW(DrawMeshTasksIndirectEXT, "meshIndirect", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, uint32_t n, uint32_t s), (c, b, o, n, s))
DRAW(DrawMeshTasksIndirectCountEXT, "meshIndirectCount", (VkCommandBuffer c, VkBuffer b, VkDeviceSize o, VkBuffer cb2, VkDeviceSize co, uint32_t n, uint32_t s), (c, b, o, cb2, co, n, s))

// ---- lookup
typedef struct { const char* name; void* wrap; void** real; } Entry;
#define E(Name) { "vk" #Name, (void*)w_##Name, (void**)&r_##Name }
#define E2(Name, Suffix) { "vk" #Name #Suffix, (void*)w_##Name, (void**)&r_##Name }   // the same call under its EXT/KHR or core name
static const Entry gTable[] = {
    E(CreateShaderModule), E(CreateFramebuffer), E(CreateGraphicsPipelines), E(BeginCommandBuffer), E(CmdBindPipeline),
    E(CmdBeginRenderPass), E(CmdSetViewport), E(CmdSetScissor), E(CmdSetDepthBias), E(CmdSetDepthBias2EXT), E(CmdSetStencilReference),
    E(CmdSetCullMode), E2(CmdSetCullMode, EXT), E(CmdSetFrontFace), E2(CmdSetFrontFace, EXT),
    E(CmdSetPrimitiveTopology), E2(CmdSetPrimitiveTopology, EXT), E(CmdSetDepthBiasEnable), E2(CmdSetDepthBiasEnable, EXT),
    E2(CmdSetDepthClampEnable, EXT), E(CmdSetRasterizerDiscardEnable), E2(CmdSetRasterizerDiscardEnable, EXT),
    E(CmdSetDepthTestEnable), E2(CmdSetDepthTestEnable, EXT), E(CmdSetDepthWriteEnable), E2(CmdSetDepthWriteEnable, EXT),
    E(CmdSetDepthCompareOp), E2(CmdSetDepthCompareOp, EXT), E(CmdSetStencilTestEnable), E2(CmdSetStencilTestEnable, EXT),
    E(CmdDraw), E(CmdDrawIndexed), E(CmdDrawIndirect), E(CmdDrawIndexedIndirect),
    E(CmdDrawIndirectCount), E2(CmdDrawIndirectCount, KHR), E(CmdDrawIndexedIndirectCount), E2(CmdDrawIndexedIndirectCount, KHR),
    E(CmdDrawIndirectByteCountEXT), E(CmdDrawMeshTasksEXT), E(CmdDrawMeshTasksIndirectEXT), E(CmdDrawMeshTasksIndirectCountEXT),
};

__attribute__((visibility("default"))) VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice device, const char* name);
static PFN_vkVoidFunction wrapFor(const char* name, PFN_vkVoidFunction real) {
    if (!real) return NULL;   // what the real library does not offer stays absent
    if (!strcmp(name, "vkGetDeviceProcAddr")) { r_gdpa = (PFN_vkGetDeviceProcAddr)real; return (PFN_vkVoidFunction)vkGetDeviceProcAddr; }
    for (size_t i = 0; i < sizeof gTable / sizeof gTable[0]; i++)
        if (!strcmp(name, gTable[i].name)) { *gTable[i].real = (void*)real; return (PFN_vkVoidFunction)gTable[i].wrap; }
    return real;
}
__attribute__((visibility("default"))) VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance instance, const char* name) {
    init();
    if (!r_gipa) return NULL;
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)vkGetInstanceProcAddr;
    return wrapFor(name, r_gipa(instance, name));
}
__attribute__((visibility("default"))) VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice device, const char* name) {
    init();
    if (!r_gdpa) return NULL;
    return wrapFor(name, r_gdpa(device, name));
}
__attribute__((destructor)) static void fini(void) { if (gOut) fflush(gOut); }
