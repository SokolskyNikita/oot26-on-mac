"""How many distinct graphics pipeline keys the recorded caches would have with extended dynamic state.

Reads saved Lichii caches (fork-v54 exports) and, for every graphics record, rebuilds the hashed key
as FixedPipelineState::Refresh would have written it at each `dyna_state` level on MoltenVK
(path-60 build: EDS1 and EDS2 without the logic-op extra; EDS3 only with dynamic depth clamp,
no dynamic blend; no VK_EXT_vertex_input_dynamic_state). It counts distinct keys and distinct
"Metal-side" combinations under each level.

Usage: python3 -I eds_keys.py CACHE.bin [CACHE.bin ...]   (prints a JSON summary)

Level rules (src/video_core/renderer_vulkan/fixed_pipeline_state.cpp/.h, prebuild worktree):
  EDS1: raw1 bit 0; DynamicState::Refresh is skipped, so dynamic_state.raw2 (stencil, depth
        test/write/func/bounds enable, front face) and raw1 cull_face/cull_enable stay 0;
        Size() stops at vertex_strides (368 bytes instead of 432).
  EDS2: + raw1 bit 1; Refresh2 returns before rasterize_enable, primitive_restart_enable and
        depth_bias_enable; topology collapses to its class representative (needs EDS1 and EDS2).
        logic_op stays (MoltenVK has no extendedDynamicState2LogicOp).
  EDS3: + raw1 bit 4 (enables); depth_clamp_disabled leaves the key (MoltenVK reports
        extendedDynamicState3DepthClampEnable). Blending stays static (no ColorBlendEnable/Equation).
"""
import collections
import json
import os
import struct
import sys

import os, subprocess
REPO = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=os.path.dirname(os.path.abspath(__file__)), text=True).strip()
HERE_TOOLS = (REPO + '/wip/shader-prebuild/local/emulator-prebuild/lichii/'
              'tools/nx2-precompile/py')
sys.path.insert(0, HERE_TOOLS)
import lichii_cache as lc  # noqa: E402
import state_model_static as sms  # noqa: E402

STATIC_LEN = 432      # offsetof(FixedPipelineState, xfb_state)
EDS_LEN = 368         # offsetof(FixedPipelineState, vertex_strides)
DS1, DS2 = 72, 76     # dynamic_state.raw1 / raw2

# TOPOLOGY_CLASS_REPRESENTATIVE_LUT (Maxwell::PrimitiveTopology values 0..14)
TOPO_CLASS = [0, 1, 2, 3, 4, 4, 4, 4, 4, 4, 10, 10, 12, 12, 14]


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def put(b, o, v):
    struct.pack_into('<I', b, o, v)


def level_state(state: bytes, level: int) -> bytes:
    """The hashed bytes of the key at `level` (0 = today's static key)."""
    b = bytearray(state[:STATIC_LEN])
    if level == 0:
        return bytes(b)
    raw1 = u32(b, 0) | 1
    put(b, DS2, 0)
    ds1 = u32(b, DS1) & ~0x7                      # cull_face, cull_enable
    if level >= 2:
        raw1 |= 2
        ds1 &= ~((1 << 3) | (1 << 4) | (1 << 5))  # primitive restart, depth bias, rasterize enable
        topo = (raw1 >> 24) & 0xF
        raw1 = (raw1 & ~(0xF << 24)) | (TOPO_CLASS[topo] << 24)
    if level >= 3:
        raw1 |= 1 << 4
        ds1 &= ~(1 << 11)                         # depth_clamp_disabled
    put(b, 0, raw1)
    put(b, DS1, ds1)
    return bytes(b[:EDS_LEN])


def rasterization_disabled(state: bytes) -> bool:
    """MoltenVK builds a pipeline with rasterizationEnabled = NO when rasterizer discard or cull
    FRONT_AND_BACK on triangles is static (MVKGraphicsPipeline::isRasterizationDisabled)."""
    ds1 = u32(state, DS1)
    rasterize_enable = (ds1 >> 5) & 1
    cull_both = ((ds1 >> 2) & 1) and (ds1 & 3) == 2
    tri = TOPO_CLASS[(u32(state, 0) >> 24) & 0xF] in (4, 12, 14)
    return (not rasterize_enable) or bool(cull_both and tri)


def metal_parts(uh: bytes, state: bytes, dynamic_stride: bool, static_raster: bool):
    """Approximate inputs of Metal's two compiled halves and of the whole pipeline object.

    Vertex half: the vertex-side shaders, the SPIR-V inputs the key feeds them (ndc, point size,
    topology class, tessellation, xfb, y negate, swizzles), the vertex descriptor (attributes,
    divisors and, with static strides only, the strides).
    Fragment half: the pixel shader and the fragment-side inputs (msaa, dual source, alpha test,
    early z, colour formats, blending). Depth format left out: measured not to recompile anything.
    Whole: both halves plus depth format and, where it is static, rasterization disabled."""
    raw1, raw2 = u32(state, 0), u32(state, 4)
    topo_class = TOPO_CLASS[(raw1 >> 24) & 0xF]
    rd = rasterization_disabled(state) if static_raster else False
    vtx = (uh[:40],                                   # unique_hashes[0..4]
           raw1 & 0x001FFFC0 & ~0x0,                  # xfb, ndc, polygon, tessellation, patch points
           topo_class, u32(state, 28),                 # point size
           raw2 & (1 << 11),                           # y negate
           state[32:64],                               # viewport swizzles
           state[64:72], state[112:368],               # enabled divisors, attributes, divisors
           None if dynamic_stride else state[368:432],
           rd)
    frag = (uh[40:48],                                 # unique_hashes[5] (pixel)
            raw1 & 0xF0200000,                         # msaa, dual source blend
            raw2 & 0x0001801E,                         # alpha test func, early z, a2c, a2one
            state[8:16], u32(state, 24), state[80:112],
            rd)
    whole = (vtx, frag, (raw2 >> 5) & 0x3F)            # + depth enable/format
    return vtx, frag, whole


def is_mesh(rec) -> bool:
    return any(e.stage in (lc.STAGE_TASK, lc.STAGE_MESH) for e in rec.envs)


def scan(paths):
    groups = ('vp', 'mesh')
    keys = {g: [set() for _ in range(4)] for g in groups}
    metal = {g: {name: set() for name in ('vtx_static', 'vtx_dyn', 'frag_static', 'frag_dyn',
                                          'whole_static', 'whole_eds1', 'whole_eds2')}
             for g in groups}
    per_file = {}
    stats = collections.Counter()
    for path in paths:
        with open(path, 'rb') as f:
            data = f.read()
        version, records = lc.parse_cache(data)
        file_keys = {g: [set() for _ in range(4)] for g in groups}
        for rec in records:
            if rec.is_compute:
                continue
            key = rec.key
            uh, st = key[:48], sms.canonical(key[48:48 + lc.FPS_SIZE])
            raw1 = u32(st, 0)
            stats['graphics_records'] += 1
            if raw1 & 0x3F:
                stats['records_with_dynamic_flags'] += 1
            if raw1 & (1 << 6):
                stats['records_with_xfb'] += 1
            if lc.fps_size(key[48:]) != STATIC_LEN:
                stats['records_not_432'] += 1
            g = 'mesh' if is_mesh(rec) else 'vp'
            for lvl in range(4):
                k = uh + level_state(st, lvl)
                keys[g][lvl].add(k)
                file_keys[g][lvl].add(k)
            vs, fs, ws = metal_parts(uh, st, dynamic_stride=False, static_raster=True)
            vd, fd, _ = metal_parts(uh, st, dynamic_stride=True, static_raster=False)
            _, _, w1 = metal_parts(uh, st, dynamic_stride=True, static_raster=True)
            m = metal[g]
            m['vtx_static'].add(vs)
            m['vtx_dyn'].add(vd)
            m['frag_static'].add(fs)
            m['frag_dyn'].add(fd)
            m['whole_static'].add(ws)
            m['whole_eds1'].add(w1)
            m['whole_eds2'].add(metal_parts(uh, st, True, False)[2])
            stats['rasterization_disabled_static'] += rasterization_disabled(st)
        per_file[os.path.basename(path)] = {
            'version': version,
            **{g: {f'L{lvl}': len(file_keys[g][lvl]) for lvl in range(4)} for g in groups}}
    return {
        'files': per_file,
        'record_stats': dict(stats),
        'union_keys': {g: {f'L{lvl}': len(keys[g][lvl]) for lvl in range(4)} for g in groups},
        'union_metal': {g: {k: len(v) for k, v in metal[g].items()} for g in groups},
    }


if __name__ == '__main__':
    print(json.dumps(scan(sys.argv[1:]), indent=1))
