"""
Space City Racing - put the Blender space car into Unreal and make it the player car.

Safe to re-run: it updates existing assets instead of duplicating them.

  1. Creates the car's materials (paint, glow, glass, ...) in /Game/SpaceCar/Materials
  2. Imports Art/Exports/SK_SpaceCar.fbx onto the template's SK_SportsCar skeleton,
     so it reuses ABP_SportsCar (spinning/steering wheels)
  3. Makes SpaceCar wheel classes sized to the new wheels
  4. Makes BP_SpaceCar (a copy of the template sports car) using the new mesh
  5. Sets BP_SpaceCar as the default pawn in the game mode

Run headless with the editor CLOSED:
  UnrealEditor-Cmd.exe SpaceCityRacing.uproject -run=pythonscript -script=Scripts/setup_space_car.py -unattended -NullRHI
"""
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FBX = os.path.join(REPO, "Art", "Exports", "SK_SpaceCar.fbx")
LOG = os.environ.get("SCR_LOG", "")

BASE = "/Game/SpaceCar"
TEMPLATE_SKELETON = "/Game/Vehicles/SportsCar/SK_SportsCar"
TEMPLATE_PA = "/Game/Vehicles/SportsCar/PA_SportsCar"
TEMPLATE_BP = "/Game/VehicleTemplate/Blueprints/SportsCar/BP_VehicleAdvSportsCar"
TEMPLATE_WHEEL_F = "/Game/VehicleTemplate/Blueprints/SportsCar/SportsCar_WheelsFront"
TEMPLATE_WHEEL_B = "/Game/VehicleTemplate/Blueprints/SportsCar/SportsCar_WheelsRear"
GAME_MODE = "/Game/VehicleTemplate/Blueprints/BP_VehicleAdvGameMode"

# Wheel physics (cm), matching the tyres modelled in Blender: key -> (radius, width)
WHEEL_SIZE = {"front": (39.0, 35.0), "rear": (40.0, 40.0)}

# The template's body/wheel meshes that BP_SpaceCar no longer needs
TEMPLATE_STATIC_PARTS = {"Chasis_Main", "Chasis_Glass", "FL_Wheel_0", "FR_Wheel_0", "BL_Wheel_0", "BR_Wheel_0"}

# name: (base colour, metallic, roughness, emissive colour, emissive strength, clear coat)
MATERIALS = {
    "M_SpaceCar_Body": ((0.03, 0.09, 0.45), 0.85, 0.22, None, 0, True),
    "M_SpaceCar_Trim": ((0.015, 0.016, 0.02), 0.6, 0.35, None, 0, False),
    "M_SpaceCar_Glass": ((0.01, 0.03, 0.05), 0.3, 0.03, None, 0, True),
    "M_SpaceCar_Glow": ((0.0, 0.7, 1.0), 0.0, 0.5, (0.0, 0.7, 1.0), 20, False),
    "M_SpaceCar_Thruster": ((1.0, 0.1, 0.5), 0.0, 0.5, (1.0, 0.1, 0.5), 30, False),
    "M_SpaceCar_Headlight": ((0.9, 0.95, 1.0), 0.0, 0.5, (0.9, 0.95, 1.0), 40, False),
    "M_SpaceCar_Tyre": ((0.012, 0.012, 0.012), 0.0, 0.85, None, 0, False),
    "M_SpaceCar_Rim": ((0.7, 0.72, 0.75), 1.0, 0.18, None, 0, False),
}

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
BEL = unreal.BlueprintEditorLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    unreal.log("SPACECAR " + msg)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def must(obj, what):
    if not obj:
        raise RuntimeError(f"missing: {what}")
    return obj


def cdo_of(bp):
    return unreal.get_default_object(BEL.generated_class(bp))


def copy_asset(src, dst):
    if EAL.does_asset_exist(dst):
        return EAL.load_asset(dst)
    return must(EAL.duplicate_asset(src, dst), f"duplicate {src} -> {dst}")


# ---------------------------------------------------------------- 1. materials
def clear_coat_properties():
    """Clear coat amount/roughness pins; their enum names vary between engine versions."""
    P = unreal.MaterialProperty
    names = [n for n in dir(P) if n.startswith("MP_")]
    for a, b in (("MP_CLEAR_COAT", "MP_CLEAR_COAT_ROUGHNESS"),
                 ("MP_CUSTOM_DATA0", "MP_CUSTOM_DATA1"),
                 ("MP_CUSTOM_DATA_0", "MP_CUSTOM_DATA_1"),
                 ("MP_CUSTOMDATA0", "MP_CUSTOMDATA1")):
        if a in names and b in names:
            return getattr(P, a), getattr(P, b)
    return None  # not exposed to Python in this engine version: paint stays standard glossy


def build_material(name, base, metallic, rough, emit, strength, clear_coat):
    folder = f"{BASE}/Materials"
    path = f"{folder}/{name}"
    if EAL.does_asset_exist(path):
        mat = EAL.load_asset(path)
        MEL.delete_all_material_expressions(mat)
    else:
        mat = AT.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())

    def vec(rgb, x, y):
        e = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, x, y)
        e.set_editor_property("constant", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
        return e

    def num(val, x, y):
        e = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, x, y)
        e.set_editor_property("r", float(val))
        return e

    P = unreal.MaterialProperty
    MEL.connect_material_property(vec(base, -500, -200), "", P.MP_BASE_COLOR)
    MEL.connect_material_property(num(metallic, -500, -50), "", P.MP_METALLIC)
    MEL.connect_material_property(num(rough, -500, 50), "", P.MP_ROUGHNESS)
    if emit:
        col, k = vec(emit, -750, 250), num(strength, -750, 400)
        mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -500, 300)
        MEL.connect_material_expressions(col, "", mul, "A")
        MEL.connect_material_expressions(k, "", mul, "B")
        MEL.connect_material_property(mul, "", P.MP_EMISSIVE_COLOR)
    coat_pins = clear_coat_properties()
    if clear_coat and coat_pins:
        mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
        MEL.connect_material_property(num(1.0, -500, 150), "", coat_pins[0])
        MEL.connect_material_property(num(0.05, -500, 200), "", coat_pins[1])
    else:
        mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    # Without this the game can't draw the material on the (skeletal) car mesh and shows it blank
    mat.set_editor_property("used_with_skeletal_mesh", True)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat, only_if_is_dirty=False)
    return mat


def build_materials():
    out = {name: build_material(name, *spec) for name, spec in MATERIALS.items()}
    log("materials:", ", ".join(out))
    return out


# ---------------------------------------------------------------- 2. mesh
def import_skeletal(fbx, name):
    """Import an FBX as a skeletal mesh on the template skeleton (no physics asset)."""
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")
    skeleton = must(EAL.load_asset(TEMPLATE_SKELETON), "template skeleton")
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    ui.set_editor_property("skeleton", skeleton)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.skeletal_mesh_import_data.set_editor_property("import_morph_targets", False)

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", fbx)
    task.set_editor_property("destination_path", f"{BASE}/Meshes")
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    task.set_editor_property("options", ui)
    AT.import_asset_tasks([task])
    log(f"import {name}:", list(task.get_editor_property("imported_object_paths")))
    return must(EAL.load_asset(f"{BASE}/Meshes/{name}"), f"imported {name}")


def import_mesh(materials):
    mesh = import_skeletal(FBX, "SK_SpaceCar")
    log("mesh skeleton:", mesh.get_editor_property("skeleton").get_path_name())

    slots = mesh.get_editor_property("materials")
    for s in slots:
        slot = str(s.get_editor_property("material_slot_name"))
        imported = str(s.get_editor_property("imported_material_slot_name"))
        mat = materials.get(slot) or materials.get(imported)
        if mat:
            s.set_editor_property("material_interface", mat)
        log(f"  slot {slot}: {'-> ' + mat.get_name() if mat else 'NO MATCH'}")
    mesh.set_editor_property("materials", slots)
    EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    return mesh


# ---------------------------------------------------------------- 2b. physics
def build_physics(mesh):
    """Use a copy of the template sports car's physics asset. The car's wheel bones sit
    exactly where the sports car's do, so its body hull and wheel joints line up."""
    # Remove leftovers from an earlier experiment (generated capsule physics + proxy mesh)
    mesh.set_editor_property("physics_asset", None)
    for old in (f"{BASE}/Meshes/SK_SpaceCar_PhysicsProxy_PhysicsAsset", f"{BASE}/Meshes/SK_SpaceCar_PhysicsProxy"):
        if EAL.does_asset_exist(old):
            log("  removing leftover:", old, EAL.delete_asset(old))
    pa = copy_asset(TEMPLATE_PA, f"{BASE}/Meshes/PA_SpaceCar")
    mesh.set_editor_property("physics_asset", pa)
    EAL.save_loaded_asset(pa, only_if_is_dirty=False)
    EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    log("physics asset:", pa.get_path_name())
    return pa


# ---------------------------------------------------------------- 3. wheels
def build_wheels():
    out = {}
    for key, src in (("front", TEMPLATE_WHEEL_F), ("rear", TEMPLATE_WHEEL_B)):
        bp = copy_asset(src, f"{BASE}/Blueprints/SpaceCar_Wheels{key.title()}")
        cdo = cdo_of(bp)
        cdo.set_editor_property("wheel_radius", WHEEL_SIZE[key][0])
        cdo.set_editor_property("wheel_width", WHEEL_SIZE[key][1])
        EAL.save_loaded_asset(bp, only_if_is_dirty=False)
        out[key] = BEL.generated_class(bp)
        log(f"wheels {key}: radius {cdo.get_editor_property('wheel_radius')} width {cdo.get_editor_property('wheel_width')}")
    return out


# ---------------------------------------------------------------- 4. vehicle blueprint
def movement_of(cdo):
    for name in ("vehicle_movement_component", "chaos_vehicle_movement", "vehicle_movement"):
        try:
            mv = cdo.get_editor_property(name)
            if mv:
                return mv
        except Exception:
            continue
    raise RuntimeError("vehicle movement component not found")


def build_blueprint(mesh, wheels):
    bp = copy_asset(TEMPLATE_BP, f"{BASE}/Blueprints/BP_SpaceCar")

    # Hide the template's static body / wheel meshes
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    SDL = unreal.SubobjectDataBlueprintFunctionLibrary
    for handle in sds.k2_gather_subobject_data_for_blueprint(bp):
        data = SDL.get_data(handle)
        obj = SDL.get_object(data)
        name = str(SDL.get_variable_name(data))
        if isinstance(obj, unreal.StaticMeshComponent) and name in TEMPLATE_STATIC_PARTS:
            obj.set_editor_property("static_mesh", None)
            log("  cleared template part:", name)

    BEL.compile_blueprint(bp)
    cdo = cdo_of(bp)

    skel_comp = cdo.get_editor_property("mesh")
    skel_comp.set_editor_property("skeletal_mesh_asset", mesh)
    # The template hides this component (its body is drawn by static meshes);
    # our body lives in the skeletal mesh, so it must be visible.
    skel_comp.set_editor_property("visible", True)
    skel_comp.set_editor_property("hidden_in_game", False)

    # Python hands back copies of array elements, so build a fresh array and set it back
    mv = movement_of(cdo)
    new_setups = []
    for w in mv.get_editor_property("wheel_setups"):
        setup = unreal.ChaosWheelSetup()
        bone = w.get_editor_property("bone_name")
        setup.set_editor_property("bone_name", bone)
        setup.set_editor_property("additional_offset", w.get_editor_property("additional_offset"))
        setup.set_editor_property(
            "wheel_class", wheels["front"] if str(bone).endswith(("FL", "FR")) else wheels["rear"])
        new_setups.append(setup)
    mv.set_editor_property("wheel_setups", new_setups)
    log("wheel setups:", [(str(s.get_editor_property("bone_name")), s.get_editor_property("wheel_class").get_name())
                          for s in mv.get_editor_property("wheel_setups")])

    EAL.save_loaded_asset(bp, only_if_is_dirty=False)
    return bp


# ---------------------------------------------------------------- 5. game mode
def set_default_pawn(bp):
    gm = must(EAL.load_asset(GAME_MODE), "game mode")
    cdo_of(gm).set_editor_property("default_pawn_class", BEL.generated_class(bp))
    EAL.save_loaded_asset(gm, only_if_is_dirty=False)


# ---------------------------------------------------------------- verify
def verify():
    bp = EAL.load_asset(f"{BASE}/Blueprints/BP_SpaceCar")
    cdo = cdo_of(bp)
    comp = cdo.get_editor_property("mesh")
    log("VERIFY BP mesh:", comp.get_editor_property("skeletal_mesh_asset").get_path_name())
    log("VERIFY BP anim:", comp.get_editor_property("anim_class").get_path_name())
    for w in movement_of(cdo).get_editor_property("wheel_setups"):
        log("VERIFY wheel:", w.get_editor_property("bone_name"), w.get_editor_property("wheel_class").get_name())
    gm = cdo_of(EAL.load_asset(GAME_MODE))
    log("VERIFY default pawn:", gm.get_editor_property("default_pawn_class").get_name())
    mesh = EAL.load_asset(f"{BASE}/Meshes/SK_SpaceCar")
    b = mesh.get_bounds()
    log("VERIFY mesh size (cm): %.0f x %.0f x %.0f" % (b.box_extent.x * 2, b.box_extent.y * 2, b.box_extent.z * 2))


def main():
    log("FBX:", FBX)
    materials = build_materials()
    mesh = import_mesh(materials)
    build_physics(mesh)
    wheels = build_wheels()
    bp = build_blueprint(mesh, wheels)
    set_default_pawn(bp)
    verify()
    log("DONE")


main()
