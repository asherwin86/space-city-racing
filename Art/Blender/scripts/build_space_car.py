"""
Space City Racing - procedural "space car" generator for Blender 5.x.

Builds a futuristic racer, rigs it for Unreal's Chaos Vehicle system
(Root bone + 4 wheel bones), renders preview images, saves an editable
.blend and exports an FBX ready to import into Unreal.

Run from a terminal:
  "E:\\Blender\\blender.exe" -b --factory-startup --python-exit-code 1 ^
      -P build_space_car.py -- <repo_root> <preview_dir>

All design numbers below are in centimetres (Unreal's unit). The car faces
+X in Blender, which becomes +X (forward) in Unreal.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------- paths
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(args[0]) if args else os.getcwd()
PREVIEW_DIR = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(REPO, "Art", "Renders")
BLEND_PATH = os.path.join(REPO, "Art", "Blender", "SpaceCar.blend")
FBX_PATH = os.path.join(REPO, "Art", "Exports", "SK_SpaceCar.fbx")

CM = 0.01  # the scene is built in metres; design numbers are cm


def v(x, y, z):
    return Vector((x * CM, y * CM, z * CM))


# ---------------------------------------------------------------- design
WHEEL_R = 34      # wheel radius
WHEEL_W = 30      # tyre width
WHEEL_X = 150     # front/rear axle distance from centre
WHEEL_Y = 103     # wheel centre distance from centreline
WHEELS = {        # bone name -> (x, y); +Y is the car's left side
    "Wheel_FL": (WHEEL_X, WHEEL_Y),
    "Wheel_FR": (WHEEL_X, -WHEEL_Y),
    "Wheel_RL": (-WHEEL_X, WHEEL_Y),
    "Wheel_RR": (-WHEEL_X, -WHEEL_Y),
}

# Body cross-sections from tail to nose: (x, half-width, bottom z, top z)
BODY = [
    (-225, 64, 32, 80),
    (-200, 74, 28, 86),
    (-140, 78, 24, 88),
    (-60, 76, 22, 90),
    (20, 72, 22, 86),
    (100, 60, 24, 72),
    (170, 46, 26, 56),
    (215, 32, 28, 45),
    (238, 14, 32, 38),
]

# Cockpit canopy cross-sections (sits on top of the body)
CANOPY = [
    (-120, 8, 78, 84),
    (-95, 30, 76, 102),
    (-50, 40, 76, 115),
    (-5, 40, 76, 117),
    (35, 32, 76, 106),
    (70, 14, 76, 88),
    (85, 4, 76, 80),
]


# ---------------------------------------------------------------- helpers
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.unit_settings.system = "METRIC"
    s.unit_settings.scale_length = 1.0
    return s


def make_material(name, color, metallic=0.0, rough=0.5, coat=0.0, emit=None, strength=0.0):
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
    put("Coat Weight", coat)
    if emit:
        put("Emission Color", (*emit, 1.0))
        put("Emission Strength", strength)
    m.diffuse_color = (*color, 1.0)
    return m


def sample_stations(st, n):
    """Smoothly resample a list of cross-sections (Catmull-Rom)."""
    out, m = [], len(st)
    for k in range(n):
        u = k / (n - 1) * (m - 1)
        i = min(int(u), m - 2)
        t = u - i
        p0, p1, p2, p3 = st[max(i - 1, 0)], st[i], st[i + 1], st[min(i + 2, m - 1)]
        out.append(tuple(
            0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                   + (-a + 3 * b - 3 * c + d) * t ** 3)
            for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


def half_width_at(st, x):
    """Linear lookup of body half-width at a given x."""
    for (x0, w0, *_), (x1, w1, *_) in zip(st, st[1:]):
        if x0 <= x <= x1:
            return w0 + (w1 - w0) * (x - x0) / (x1 - x0)
    return st[0][1] if x < st[0][0] else st[-1][1]


def superellipse(a, e):
    c, s = math.cos(a), math.sin(a)
    return math.copysign(abs(c) ** (2 / e), c), math.copysign(abs(s) ** (2 / e), s)


def loft(stations, rings, around, expo, face_mat=None):
    """Skin a series of rounded-box cross-sections into a closed mesh."""
    bm = bmesh.new()
    grid = []
    for x, w, zb, zt in sample_stations(stations, rings):
        zc, h = (zb + zt) / 2, (zt - zb) / 2
        row = []
        for j in range(around):
            cy, sz = superellipse(2 * math.pi * j / around, expo)
            row.append(bm.verts.new(v(x, w * cy, zc + h * sz)))
        grid.append(row)
    for i in range(rings - 1):
        for j in range(around):
            jn = (j + 1) % around
            f = bm.faces.new((grid[i][j], grid[i][jn], grid[i + 1][jn], grid[i + 1][j]))
            if face_mat:
                f.material_index = face_mat(i, j)
    bm.faces.new(grid[0])
    bm.faces.new(list(reversed(grid[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return bm


def faces_of(verts):
    return {f for vt in verts for f in vt.link_faces}


def cylinder(bm, radius, depth, center, axis="Y", segments=32, radius2=None, mat_index=0):
    rot = {
        "X": Matrix.Rotation(math.radians(90), 4, "Y"),
        "Y": Matrix.Rotation(math.radians(90), 4, "X"),
        "Z": Matrix.Identity(4),
    }[axis]
    res = bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius * CM, radius2=(radius if radius2 is None else radius2) * CM,
        depth=depth * CM, matrix=Matrix.Translation(center) @ rot)
    for f in faces_of(res["verts"]):
        f.material_index = mat_index
    return res["verts"]


def box(bm, center, size_cm, mat_index=0, bevel_cm=0.0):
    sx, sy, sz = size_cm
    res = bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.Translation(center) @ Matrix.Diagonal(Vector((sx * CM, sy * CM, sz * CM, 1.0))))
    for f in faces_of(res["verts"]):
        f.material_index = mat_index
    if bevel_cm:
        edges = list({e for vt in res["verts"] for e in vt.link_edges})
        try:
            bmesh.ops.bevel(bm, geom=edges, offset=bevel_cm * CM, segments=2,
                            profile=0.5, affect="EDGES", clamp_overlap=True)
        except Exception as exc:  # bevel is cosmetic only
            print("bevel skipped:", exc)
    return res["verts"]


def arc_shell(bm, cx, cy, cz, r_in, r_out, width, a0, a1, seg, mat_index=0):
    """Curved fender that arcs over a wheel (angles in XZ, 0 = front)."""
    rows = []
    for k in range(seg + 1):
        a = math.radians(a0 + (a1 - a0) * k / seg)
        ca, sa = math.cos(a), math.sin(a)
        rows.append([bm.verts.new(v(cx + r * ca, cy + dy, cz + r * sa))
                     for r, dy in ((r_in, -width / 2), (r_out, -width / 2),
                                   (r_out, width / 2), (r_in, width / 2))])
    new_faces = []
    for k in range(seg):
        a, b = rows[k], rows[k + 1]
        for i in range(4):
            i2 = (i + 1) % 4
            new_faces.append(bm.faces.new((a[i], a[i2], b[i2], b[i])))
    new_faces.append(bm.faces.new(rows[0]))
    new_faces.append(bm.faces.new(list(reversed(rows[-1]))))
    for f in new_faces:
        f.material_index = mat_index


def make_object(name, bm, mats, subdiv=0, sharp_deg=35):
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if subdiv:
        mod = ob.modifiers.new("Subdiv", "SUBSURF")
        mod.levels = mod.render_levels = subdiv
        dg = bpy.context.evaluated_depsgraph_get()
        baked = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        ob.modifiers.clear()
        old = ob.data
        ob.data = baked
        bpy.data.meshes.remove(old)
        baked.name = name
    for p in ob.data.polygons:
        p.use_smooth = True
    try:
        ob.data.set_sharp_from_angle(angle=math.radians(sharp_deg))
    except Exception as exc:
        print("sharp-from-angle skipped:", exc)
    return ob


# ---------------------------------------------------------------- build
def build_car(M):
    parts = []  # (object, bone name)

    # Body: rounded fuselage with a glowing strip down each side
    n_rings, n_around = 40, 48

    def body_mat(i, j):
        return 1 if (6 <= i <= 30 and j in (0, n_around // 2)) else 0

    body = make_object("Body", loft(BODY, n_rings, n_around, 3.5, body_mat),
                       [M["body"], M["glow"]], subdiv=1)
    parts.append((body, "Root"))

    canopy = make_object("Canopy", loft(CANOPY, 20, 24, 2.5), [M["glass"]], subdiv=2)
    parts.append((canopy, "Root"))

    # Rear thrusters with hot-pink cores
    bm = bmesh.new()
    for side in (1, -1):
        cylinder(bm, 16, 40, v(-235, 40 * side, 57), "X", 32, mat_index=0)
        cylinder(bm, 18, 6, v(-253, 40 * side, 57), "X", 32, radius2=16, mat_index=0)
        cylinder(bm, 12, 2, v(-256.5, 40 * side, 57), "X", 32, mat_index=1)
    parts.append((make_object("Thrusters", bm, [M["trim"], M["thruster"]]), "Root"))

    # Rear wing on two pylons, with end plates and a glowing trailing edge
    bm = bmesh.new()
    box(bm, v(-210, 0, 131), (40, 220, 6), 0, bevel_cm=1.5)
    box(bm, v(-231, 0, 131), (2, 200, 3), 1)
    for side in (1, -1):
        box(bm, v(-205, 45 * side, 105), (12, 5, 46), 0, bevel_cm=1.0)
        box(bm, v(-208, 111 * side, 127.5), (50, 3, 35), 0, bevel_cm=1.0)
    parts.append((make_object("Wing", bm, [M["trim"], M["glow"]]), "Root"))

    # Front splitter and headlight strips
    bm = bmesh.new()
    box(bm, v(205, 0, 24), (70, 150, 3), 0, bevel_cm=1.0)
    for side in (1, -1):
        box(bm, v(212, 26 * side, 44), (20, 14, 3), 1)
    parts.append((make_object("Nose", bm, [M["trim"], M["headlight"]]), "Root"))

    # Wheel fenders (fixed to the body) with struts back to the fuselage
    bm = bmesh.new()
    for x, y in WHEELS.values():
        side = 1 if y > 0 else -1
        arc_shell(bm, x, y, WHEEL_R, 39, 44, 38, 10, 170, 24, 0)
        inner = half_width_at(BODY, x) - 6
        outer = abs(y) - 15
        box(bm, v(x, side * (inner + outer) / 2, WHEEL_R + 36), (14, outer - inner, 6), 0, bevel_cm=1.0)
    parts.append((make_object("Fenders", bm, [M["trim"]]), "Root"))

    # Wheels: tyre + glowing ring + metal rim, one object per wheel bone
    for bone, (x, y) in WHEELS.items():
        bm = bmesh.new()
        c = v(x, y, WHEEL_R)
        tyre = cylinder(bm, WHEEL_R, WHEEL_W, c, "Y", 40, mat_index=0)
        edges = [e for e in {e for vt in tyre for e in vt.link_edges}
                 if len(e.link_faces) == 2 and e.calc_face_angle(0) > math.radians(60)]
        try:
            bmesh.ops.bevel(bm, geom=edges, offset=4 * CM, segments=3,
                            profile=0.5, affect="EDGES", clamp_overlap=True)
        except Exception as exc:
            print("tyre bevel skipped:", exc)
        cylinder(bm, 25, WHEEL_W + 2, c, "Y", 40, mat_index=1)
        cylinder(bm, 21, WHEEL_W + 3.5, c, "Y", 40, mat_index=2)
        cylinder(bm, 7, WHEEL_W + 5, c, "Y", 20, mat_index=0)
        parts.append((make_object(bone, bm, [M["tyre"], M["glow"], M["rim"]]), bone))

    return parts


def join_and_rig(parts):
    scene = bpy.context.scene
    vl = bpy.context.view_layer

    for ob, bone in parts:
        vg = ob.vertex_groups.new(name=bone)
        vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")

    objs = [ob for ob, _ in parts]
    main = objs[0]
    for ob in objs:
        ob.select_set(True)
    vl.objects.active = main
    with bpy.context.temp_override(active_object=main, object=main,
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.join()
    car = main
    car.name = car.data.name = "SK_SpaceCar"

    # Armature must be named "Armature" so Unreal doesn't add an extra root bone
    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", arm_data)
    scene.collection.objects.link(arm)
    vl.objects.active = arm
    arm.select_set(True)
    with bpy.context.temp_override(active_object=arm, object=arm):
        bpy.ops.object.mode_set(mode="EDIT")
        root = arm_data.edit_bones.new("Root")
        root.head, root.tail = v(0, 0, 0), v(0, 0, 50)
        for bone, (x, y) in WHEELS.items():
            b = arm_data.edit_bones.new(bone)
            b.head, b.tail = v(x, y, WHEEL_R), v(x, y, WHEEL_R + 30)
            b.parent = root
        bpy.ops.object.mode_set(mode="OBJECT")

    car.parent = arm
    mod = car.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return arm, car


# ---------------------------------------------------------------- preview scene
def ground_material():
    m = bpy.data.materials.new("M_Ground")
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    bsdf = next(n for n in N if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    bsdf.inputs["Base Color"].default_value = (0.006, 0.007, 0.012, 1)
    bsdf.inputs["Roughness"].default_value = 0.45
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sep.inputs[0])

    def grid_line(axis_socket):
        mul = N.new("ShaderNodeMath"); mul.operation = "MULTIPLY"; mul.inputs[1].default_value = 0.5
        fr = N.new("ShaderNodeMath"); fr.operation = "FRACT"
        lt = N.new("ShaderNodeMath"); lt.operation = "LESS_THAN"; lt.inputs[1].default_value = 0.02
        L.new(axis_socket, mul.inputs[0]); L.new(mul.outputs[0], fr.inputs[0]); L.new(fr.outputs[0], lt.inputs[0])
        return lt.outputs[0]

    mx = N.new("ShaderNodeMath"); mx.operation = "MAXIMUM"
    L.new(grid_line(sep.outputs["X"]), mx.inputs[0])
    L.new(grid_line(sep.outputs["Y"]), mx.inputs[1])
    em = N.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.55, 0.1, 1.0, 1)
    em.inputs["Strength"].default_value = 3.0
    mix = N.new("ShaderNodeMixShader")
    L.new(mx.outputs[0], mix.inputs[0])
    L.new(bsdf.outputs[0], mix.inputs[1])
    L.new(em.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs["Surface"])
    return m


def setup_preview_scene():
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    print("render engine:", scene.render.engine)
    for attr, val in (("taa_render_samples", 64), ("use_raytracing", True), ("use_gtao", True)):
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
        bg.inputs[0].default_value = (0.006, 0.008, 0.025, 1)
        bg.inputs[1].default_value = 1.0

    me = bpy.data.meshes.new("Ground")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=50.0)
    bm.to_mesh(me); bm.free()
    me.materials.append(ground_material())
    ground = bpy.data.objects.new("Ground", me)
    scene.collection.objects.link(ground)

    target = bpy.data.objects.new("CameraTarget", None)
    target.location = (0, 0, 0.55)
    scene.collection.objects.link(target)

    def aim(ob):
        c = ob.constraints.new("TRACK_TO")
        c.target, c.track_axis, c.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"

    for name, loc, energy, size, color in (
        ("Key", (3.5, -5.0, 5.5), 1500, 4.0, (1.0, 0.97, 0.92)),
        ("Rim", (-5.0, 3.5, 3.5), 3000, 3.0, (0.6, 0.8, 1.0)),
        ("Fill", (2.0, 6.0, 2.0), 600, 5.0, (1.0, 0.6, 0.9)),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        scene.collection.objects.link(lo)
        aim(lo)

    cd = bpy.data.cameras.new("Camera")
    cd.lens = 50
    cam = bpy.data.objects.new("Camera", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    aim(cam)
    return cam


def render_previews(cam):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    for name, loc in (
        ("front_3q", (6.2, -5.6, 2.0)),
        ("side", (0.2, -9.2, 1.0)),
        ("rear_3q", (-6.4, 5.4, 2.6)),
    ):
        cam.location = loc
        path = os.path.join(PREVIEW_DIR, f"space_car_{name}.png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("rendered:", path)
    cam.location = (6.2, -5.6, 2.0)


# ---------------------------------------------------------------- export
def world_bounds(ob):
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    return [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]


def export_for_unreal(arm, car):
    """Rescale to 1 unit = 1 cm (Unreal's unit) so the skeleton imports at scale 1."""
    scene = bpy.context.scene
    scene.unit_settings.scale_length = 0.01
    scene.unit_settings.length_unit = "CENTIMETERS"
    arm.scale = (100, 100, 100)
    objs = [arm, car]
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    with bpy.context.temp_override(active_object=arm, object=arm,
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    print("export size (cm, LxWxH): %.0f x %.0f x %.0f" % tuple(world_bounds(car)))

    os.makedirs(os.path.dirname(FBX_PATH), exist_ok=True)
    with bpy.context.temp_override(active_object=arm, object=arm,
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.export_scene.fbx(
            filepath=FBX_PATH, use_selection=True, object_types={"ARMATURE", "MESH"},
            apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
            axis_forward="-Z", axis_up="Y", use_mesh_modifiers=True,
            mesh_smooth_type="FACE", add_leaf_bones=False,
            primary_bone_axis="Y", secondary_bone_axis="X",
            use_armature_deform_only=True, bake_anim=False)
    print("exported:", FBX_PATH)


def verify_fbx():
    """Re-import the FBX into an empty scene and report what Unreal will see."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=FBX_PATH)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    print("VERIFY armatures:", [a.name for a in arms])
    for a in arms:
        for b in a.data.bones:
            h = a.matrix_world @ b.head_local
            print("VERIFY bone %-9s parent=%-5s head(m)=(%.2f, %.2f, %.2f)"
                  % (b.name, b.parent.name if b.parent else "-", h.x, h.y, h.z))
    for m in meshes:
        print("VERIFY mesh %s: %d tris, size(m) %.2f x %.2f x %.2f, groups=%s, materials=%s" % (
            m.name, sum(len(p.vertices) - 2 for p in m.data.polygons), *world_bounds(m),
            [g.name for g in m.vertex_groups], [s.material.name for s in m.material_slots if s.material]))


# ---------------------------------------------------------------- main
def main():
    reset_scene()
    M = {
        "body": make_material("M_SpaceCar_Body", (0.03, 0.09, 0.45), metallic=0.85, rough=0.22, coat=1.0),
        "trim": make_material("M_SpaceCar_Trim", (0.015, 0.016, 0.02), metallic=0.6, rough=0.35),
        "glass": make_material("M_SpaceCar_Glass", (0.01, 0.03, 0.05), metallic=0.3, rough=0.03, coat=1.0),
        "glow": make_material("M_SpaceCar_Glow", (0.0, 0.7, 1.0), emit=(0.0, 0.7, 1.0), strength=4),
        "thruster": make_material("M_SpaceCar_Thruster", (1.0, 0.1, 0.5), emit=(1.0, 0.1, 0.5), strength=6),
        "headlight": make_material("M_SpaceCar_Headlight", (0.9, 0.95, 1.0), emit=(0.9, 0.95, 1.0), strength=10),
        "tyre": make_material("M_SpaceCar_Tyre", (0.012, 0.012, 0.012), rough=0.85),
        "rim": make_material("M_SpaceCar_Rim", (0.7, 0.72, 0.75), metallic=1.0, rough=0.18),
    }
    parts = build_car(M)
    arm, car = join_and_rig(parts)
    print("car size (m, LxWxH): %.2f x %.2f x %.2f" % tuple(world_bounds(car)))
    print("triangles:", sum(len(p.vertices) - 2 for p in car.data.polygons))

    cam = setup_preview_scene()
    render_previews(cam)

    os.makedirs(os.path.dirname(BLEND_PATH), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, compress=True)
    print("saved:", BLEND_PATH)

    export_for_unreal(arm, car)
    verify_fbx()


main()
