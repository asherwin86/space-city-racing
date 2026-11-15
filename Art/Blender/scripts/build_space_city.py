"""
Space City Racing - procedural neon city + race track generator for Blender 5.x.

Builds a closed circuit (road, glowing curbs, barriers, start gantry) through a
grid of neon skyscrapers, renders previews, saves an editable .blend and
exports static-mesh FBX files (1 unit = 1 cm) plus track_info.json for Unreal.

Run:
  "E:\\Blender\\blender.exe" -b --factory-startup --python-exit-code 1 ^
      -P build_space_city.py -- <repo_root> <preview_dir>

Design numbers are in metres. +X/+Y in Blender become +X/-Y in Unreal.
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------- paths
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(args[0]) if args else os.getcwd()
PREVIEW_DIR = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(REPO, "Art", "Renders")
BLEND_PATH = os.path.join(REPO, "Art", "Blender", "SpaceCity.blend")
EXPORT_DIR = os.path.join(REPO, "Art", "Exports", "SpaceCity")

# ---------------------------------------------------------------- design (metres)
SEED = 7
# Track centre line, driven in this order and looped back to the start
CONTROL = [
    (0, 0, 0), (180, 0, 0), (300, 20, 0), (360, 110, 2), (330, 220, 5),
    (220, 260, 6), (120, 220, 5), (60, 300, 3), (-60, 330, 1), (-180, 280, 0),
    (-230, 160, 0), (-170, 70, 0), (-90, 10, 0),
]
STEP = 2.0          # metres between track cross-sections
ROAD_W = 14.0       # drivable width
CURB_W = 0.8        # glowing curb on each side
CURB_H = 0.06
CURB_STRIPE = 6.0   # curb colour alternates every N metres
BARRIER_W = 0.5
BARRIER_H = 1.1
GROUND_Z = -0.3     # ground plane height; barrier skirts reach below it
GANTRY_H = 9.0

CITY_MARGIN = 300.0   # how far the city extends beyond the track's bounds
CITY_CELL = 36.0      # city block grid spacing
NEON = ["neon_cyan", "neon_magenta", "neon_purple", "neon_amber"]


# ---------------------------------------------------------------- materials
def make_material(name, color, metallic=0.0, rough=0.5, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    p = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")

    def put(key, val):
        if key in p.inputs:
            p.inputs[key].default_value = val

    put("Base Color", (*color, 1.0))
    put("Metallic", metallic)
    put("Roughness", rough)
    if emit:
        put("Emission Color", (*emit, 1.0))
        put("Emission Strength", strength)
    m.diffuse_color = (*color, 1.0)
    return m


def build_materials():
    return {
        "road": make_material("M_City_Road", (0.018, 0.018, 0.022), rough=0.55),
        "curb_a": make_material("M_City_CurbCyan", (0.0, 0.8, 1.0), emit=(0.0, 0.8, 1.0), strength=3),
        "curb_b": make_material("M_City_CurbMagenta", (1.0, 0.1, 0.7), emit=(1.0, 0.1, 0.7), strength=3),
        "barrier": make_material("M_City_Barrier", (0.05, 0.05, 0.07), metallic=0.5, rough=0.4),
        "start": make_material("M_City_StartLine", (0.9, 0.95, 1.0), emit=(0.9, 0.95, 1.0), strength=6),
        "building": make_material("M_City_Building", (0.03, 0.035, 0.05), metallic=0.6, rough=0.25),
        "ground": make_material("M_City_Ground", (0.008, 0.008, 0.012), rough=0.8),
        "beacon": make_material("M_City_BeaconRed", (1.0, 0.05, 0.02), emit=(1.0, 0.05, 0.02), strength=8),
        "neon_cyan": make_material("M_City_NeonCyan", (0.0, 0.8, 1.0), emit=(0.0, 0.8, 1.0), strength=6),
        "neon_magenta": make_material("M_City_NeonMagenta", (1.0, 0.1, 0.7), emit=(1.0, 0.1, 0.7), strength=6),
        "neon_purple": make_material("M_City_NeonPurple", (0.5, 0.15, 1.0), emit=(0.5, 0.15, 1.0), strength=6),
        "neon_amber": make_material("M_City_NeonAmber", (1.0, 0.45, 0.05), emit=(1.0, 0.45, 0.05), strength=6),
    }


# ---------------------------------------------------------------- track path
def catmull_closed(pts, sub=60):
    n, out = len(pts), []
    for i in range(n):
        p0, p1, p2, p3 = (Vector(pts[(i + k) % n]) for k in (-1, 0, 1, 2))
        for s in range(sub):
            t = s / sub
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return out


def resample_closed(dense, step):
    loop = dense + [dense[0]]
    cum = [0.0]
    for a, b in zip(loop, loop[1:]):
        cum.append(cum[-1] + (b - a).length)
    length = cum[-1]
    n = max(4, int(length // step))
    step = length / n
    out, j = [], 0
    for k in range(n):
        s = k * step
        while cum[j + 1] < s:
            j += 1
        t = (s - cum[j]) / (cum[j + 1] - cum[j])
        out.append(loop[j].lerp(loop[j + 1], t))
    return out, length, step


def track_frames():
    pts, length, step = resample_closed(catmull_closed(CONTROL), STEP)
    n = len(pts)
    frames = []
    for k in range(n):
        t = (pts[(k + 1) % n] - pts[k - 1])
        t.z = 0
        t.normalize()
        left = Vector((-t.y, t.x, 0.0))
        frames.append((pts[k], t, left))
    return frames, length, step


# ---------------------------------------------------------------- mesh helpers
def sweep(bm, frames, profile, mat_fn):
    """Sweep a cross-section (list of (lateral offset, height)) around the closed track.
    Profiles go from the driver's left to right so faces point outwards/upwards.
    A height of None means 'down to below the ground'."""
    rings = []
    for p, _t, left in frames:
        ring = []
        for off, dz in profile:
            z = (GROUND_Z - 0.4) if dz is None else p.z + dz
            q = p + left * off
            ring.append(bm.verts.new((q.x, q.y, z)))
        rings.append(ring)
    n = len(rings)
    for k in range(n):
        a, b = rings[k], rings[(k + 1) % n]
        for j in range(len(profile) - 1):
            f = bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
            f.material_index = mat_fn(k, j)


def obox(bm, center, fwd, left, sx, sy, sz, mat_index):
    """Box oriented along the track (sx along fwd, sy along left, sz up)."""
    up = Vector((0, 0, 1))
    m = Matrix((
        (fwd.x * sx, left.x * sy, up.x * sz, center.x),
        (fwd.y * sx, left.y * sy, up.y * sz, center.y),
        (fwd.z * sx, left.z * sy, up.z * sz, center.z),
        (0, 0, 0, 1)))
    res = bmesh.ops.create_cube(bm, size=1.0, matrix=m)
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat_index


def abox(bm, x0, y0, z0, x1, y1, z1, mat_index):
    obox(bm, Vector(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)),
         Vector((1, 0, 0)), Vector((0, 1, 0)), x1 - x0, y1 - y0, z1 - z0, mat_index)


def make_object(name, bm, mats, sharp_deg=30):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    except Exception as exc:
        print("sharp-from-angle skipped:", exc)
    return ob


# ---------------------------------------------------------------- track
def build_track(M, frames, step):
    hw, c, bw, bh = ROAD_W / 2, CURB_W, BARRIER_W, BARRIER_H

    # Road surface + glowing curbs
    bm = bmesh.new()
    road_profile = [(hw + c, CURB_H), (hw, CURB_H), (hw, 0.0), (-hw, 0.0),
                    (-hw, CURB_H), (-hw - c, CURB_H)]

    def road_mat(k, j):
        if j == 2:
            return 0
        return 1 if int(k * step // CURB_STRIPE) % 2 == 0 else 2

    sweep(bm, frames, road_profile, road_mat)
    # Start / finish line
    p, t, left = frames[0]
    obox(bm, p + Vector((0, 0, 0.015)), t, left, 1.5, ROAD_W, 0.03, 3)
    road = make_object("SM_Track_Road", bm, [M["road"], M["curb_a"], M["curb_b"], M["start"]])

    # Barriers (body + neon top) and a skirt down into the ground
    bm = bmesh.new()
    left_profile = [(hw + c + bw, None), (hw + c + bw, 0.0), (hw + c + bw, bh), (hw + c, bh), (hw + c, CURB_H)]
    right_profile = [(-hw - c, CURB_H), (-hw - c, bh), (-hw - c - bw, bh), (-hw - c - bw, 0.0), (-hw - c - bw, None)]
    sweep(bm, frames, left_profile, lambda k, j: 1 if j == 2 else 0)
    sweep(bm, frames, right_profile, lambda k, j: 1 if j == 1 else 0)

    # Start gantry: two pillars and a glowing beam
    side = hw + c + bw + 1.5
    for s in (1, -1):
        base = p + left * (s * side)
        obox(bm, Vector((base.x, base.y, (GROUND_Z + GANTRY_H + 1.2) / 2)), t, left, 1.2, 1.2,
             GANTRY_H + 1.2 - GROUND_Z, 0)
    obox(bm, Vector((p.x, p.y, p.z + GANTRY_H + 0.6)), t, left, 1.2, 2 * side + 1.2, 1.2, 0)
    obox(bm, Vector((p.x, p.y, p.z + GANTRY_H + 0.6)) - t * 0.65, t, left, 0.1, 2 * side - 1.0, 0.5, 2)
    obox(bm, Vector((p.x, p.y, p.z + GANTRY_H + 0.6)) + t * 0.65, t, left, 0.1, 2 * side - 1.0, 0.5, 2)
    barriers = make_object("SM_Track_Barriers", bm, [M["barrier"], M["neon_purple"], M["start"]])
    return road, barriers


# ---------------------------------------------------------------- city
class TrackIndex:
    """Fast 'distance to the track centre line' lookups on a coarse grid."""

    def __init__(self, frames, cell=25.0):
        self.cell = cell
        self.grid = {}
        for p, _t, _l in frames:
            self.grid.setdefault((int(p.x // cell), int(p.y // cell)), []).append((p.x, p.y))

    def dist(self, x, y, radius):
        c, r = self.cell, int(radius // self.cell) + 1
        cx, cy = int(x // c), int(y // c)
        best = float("inf")
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                for px, py in self.grid.get((i, j), ()):
                    d = (px - x) ** 2 + (py - y) ** 2
                    if d < best:
                        best = d
        return math.sqrt(best)


def add_building(bm, rng, x, y, w, d, h, neon_idx):
    x0, x1, y0, y1 = x - w / 2, x + w / 2, y - d / 2, y + d / 2
    abox(bm, x0, y0, GROUND_Z - 0.5, x1, y1, h, 0)               # tower
    gap = rng.uniform(10, 18)
    z = rng.uniform(6, 12)
    while z < h - 3:                                              # neon bands
        abox(bm, x0 - 0.15, y0 - 0.15, z, x1 + 0.15, y1 + 0.15, z + 0.6, neon_idx)
        z += gap
    if rng.random() < 0.35:                                       # glowing corner strips
        for cx, cy in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
            abox(bm, cx - 0.35, cy - 0.35, 0, cx + 0.35, cy + 0.35, h, neon_idx)
    top = h
    if rng.random() < 0.4:                                        # set-back crown
        s = rng.uniform(0.5, 0.75)
        th = rng.uniform(6, 20)
        abox(bm, x - w * s / 2, y - d * s / 2, h, x + w * s / 2, y + d * s / 2, h + th, 0)
        abox(bm, x - w * s / 2 - 0.15, y - d * s / 2 - 0.15, h + th - 1.0,
             x + w * s / 2 + 0.15, y + d * s / 2 + 0.15, h + th - 0.4, neon_idx)
        top = h + th
    if h > 90 and rng.random() < 0.6:                             # antenna + red beacon
        ah = rng.uniform(8, 25)
        abox(bm, x - 0.3, y - 0.3, top, x + 0.3, y + 0.3, top + ah, 0)
        abox(bm, x - 0.9, y - 0.9, top + ah, x + 0.9, y + 0.9, top + ah + 1.4, 1)


def build_city(M, frames):
    rng = random.Random(SEED)
    idx = TrackIndex(frames)
    xs = [p.x for p, _t, _l in frames]
    ys = [p.y for p, _t, _l in frames]
    xmin, xmax = min(xs) - CITY_MARGIN, max(xs) + CITY_MARGIN
    ymin, ymax = min(ys) - CITY_MARGIN, max(ys) + CITY_MARGIN
    midx, midy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    track_clear = ROAD_W / 2 + CURB_W + BARRIER_W + 5.0

    # Four chunks (NE/NW/SE/SW) so Unreal can cull parts of the city you can't see
    chunks = {k: bmesh.new() for k in ("NE", "NW", "SE", "SW")}
    count = 0
    gx = xmin
    while gx < xmax:
        gy = ymin
        while gy < ymax:
            x = gx + rng.uniform(-6, 6)
            y = gy + rng.uniform(-6, 6)
            w, d = rng.uniform(14, 30), rng.uniform(14, 30)
            dist = idx.dist(x, y, 80)
            far = dist > 200
            if dist >= track_clear + 0.75 * max(w, d) and not (far and rng.random() < 0.35):
                h = rng.uniform(25, 90)
                if rng.random() < (0.35 if dist < 90 else 0.18):
                    h = rng.uniform(110, 230)
                key = ("N" if y >= midy else "S") + ("E" if x >= midx else "W")
                add_building(chunks[key], rng, x, y, w, d, h, 2 + rng.randrange(len(NEON)))
                count += 1
            gy += CITY_CELL
        gx += CITY_CELL

    mats = [M["building"], M["beacon"]] + [M[n] for n in NEON]
    objs = [make_object(f"SM_City_Buildings_{k}", bm, mats, sharp_deg=20) for k, bm in chunks.items()]

    # Ground plane under everything
    bm = bmesh.new()
    pad = 200
    abox(bm, xmin - pad, ymin - pad, GROUND_Z - 1.0, xmax + pad, ymax + pad, GROUND_Z, 0)
    ground = make_object("SM_City_Ground", bm, [M["ground"]])
    print(f"buildings: {count}")
    return objs + [ground]


# ---------------------------------------------------------------- preview
def setup_preview(frames):
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    for attr, val in (("taa_render_samples", 48), ("use_raytracing", True), ("use_gtao", True)):
        try:
            setattr(scene.eevee, attr, val)
        except Exception:
            pass
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds.new("World")
    scene.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.012, 0.008, 0.035, 1)
        bg.inputs[1].default_value = 1.0
    moon = bpy.data.lights.new("Moon", "SUN")
    moon.energy, moon.color = 0.4, (0.6, 0.7, 1.0)
    mo = bpy.data.objects.new("Moon", moon)
    mo.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(mo)
    cd = bpy.data.cameras.new("Camera")
    cd.clip_end = 5000
    cam = bpy.data.objects.new("Camera", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def look(cam, eye, target, lens):
    cam.location = eye
    d = Vector(target) - Vector(eye)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens


def render_previews(cam, frames):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    xs = [p.x for p, _t, _l in frames]
    ys = [p.y for p, _t, _l in frames]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    p0, t0, l0 = frames[0]
    pk, tk, lk = frames[len(frames) // 3]
    views = {
        "aerial": ((cx, cy - 380, 1250), (cx, cy - 20, 0), 22),
        "start": (tuple(p0 - t0 * 14 + Vector((0, 0, 3.2))), tuple(p0 + t0 * 40 + Vector((0, 0, 1.5))), 24),
        "corner": (tuple(pk - tk * 30 + lk * 20 + Vector((0, 0, 18))), tuple(pk + tk * 30), 24),
    }
    for name, (eye, target, lens) in views.items():
        look(cam, eye, target, lens)
        path = os.path.join(PREVIEW_DIR, f"space_city_{name}.png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("rendered:", path)


# ---------------------------------------------------------------- export
def export_for_unreal(objs, frames, length):
    scene = bpy.context.scene
    os.makedirs(EXPORT_DIR, exist_ok=True)
    scene.unit_settings.scale_length = 0.01
    scene.unit_settings.length_unit = "CENTIMETERS"
    for ob in objs:
        ob.scale = (100, 100, 100)
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    with bpy.context.temp_override(active_object=objs[0], object=objs[0],
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for ob in objs:
        path = os.path.join(EXPORT_DIR, ob.name + ".fbx")
        with bpy.context.temp_override(active_object=ob, object=ob,
                                       selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.export_scene.fbx(
                filepath=path, use_selection=True, object_types={"MESH"},
                apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
                axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE", bake_anim=False)
        print("exported: %s (%d tris)" % (path, sum(len(p.vertices) - 2 for p in ob.data.polygons)))

    # Start position for Unreal (cm; Blender +Y becomes Unreal -Y)
    p, t, _l = frames[0]
    yaw = -math.degrees(math.atan2(t.y, t.x))
    info = {
        "track_length_m": round(length, 1),
        "start_location_cm": [round(p.x * 100 - t.x * 800, 1), round(-(p.y * 100 - t.y * 800), 1),
                              round(p.z * 100 + 60, 1)],
        "start_yaw_deg": round(yaw, 2),
        "road_width_m": ROAD_W,
        "meshes": [ob.name for ob in objs],
    }
    with open(os.path.join(EXPORT_DIR, "track_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print("track info:", info)


def verify():
    for ob_name in sorted(os.listdir(EXPORT_DIR)):
        if not ob_name.endswith(".fbx"):
            continue
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=os.path.join(EXPORT_DIR, ob_name))
        ob = next(o for o in bpy.data.objects if o.type == "MESH")
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        size = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
        print("VERIFY %-26s size(m) %7.1f x %7.1f x %6.1f  materials=%d"
              % (ob_name, *size, len(ob.material_slots)))


# ---------------------------------------------------------------- main
def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.scale_length = 1.0
    M = build_materials()
    frames, length, step = track_frames()
    print("track length: %.0f m, %d sections" % (length, len(frames)))
    road, barriers = build_track(M, frames, step)
    objs = [road, barriers] + build_city(M, frames)

    cam = setup_preview(frames)
    render_previews(cam, frames)
    os.makedirs(os.path.dirname(BLEND_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, compress=True)
    print("saved:", BLEND_PATH)

    export_for_unreal(objs, frames, length)
    verify()


main()
