"""
Space City Racing - build the neon city level in Unreal from the Blender exports.

Safe to re-run: it updates existing assets and rebuilds the level's actors.

  1. Creates the city materials (road, glowing curbs, neon, buildings, ...)
  2. Imports Art/Exports/SpaceCity/*.fbx as static meshes with full-detail collision
  3. Builds /Game/SpaceCity/Maps/Lvl_SpaceCity: meshes, night lighting, fog,
     post-processing and a PlayerStart on the grid
  4. Makes it the map the game and editor open with

Run headless with the editor CLOSED:
  UnrealEditor-Cmd.exe SpaceCityRacing.uproject -run=pythonscript -script=Scripts/setup_space_city.py -unattended -NullRHI
"""
import json
import os
import re

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(PROJECT_DIR, ".."))
EXPORT_DIR = os.path.join(REPO, "Art", "Exports", "SpaceCity")
LOG = os.environ.get("SCR_LOG", "")

BASE = "/Game/SpaceCity"
LEVEL = f"{BASE}/Maps/Lvl_SpaceCity"
GAME_MODE = "/Game/VehicleTemplate/Blueprints/BP_VehicleAdvGameMode"

# name: (base colour, metallic, roughness, emissive colour, emissive strength)
MATERIALS = {
    "M_City_Road": ((0.018, 0.018, 0.022), 0.0, 0.55, None, 0),
    "M_City_CurbCyan": ((0.0, 0.8, 1.0), 0.0, 0.5, (0.0, 0.8, 1.0), 12),
    "M_City_CurbMagenta": ((1.0, 0.1, 0.7), 0.0, 0.5, (1.0, 0.1, 0.7), 12),
    "M_City_Barrier": ((0.05, 0.05, 0.07), 0.5, 0.4, None, 0),
    "M_City_StartLine": ((0.9, 0.95, 1.0), 0.0, 0.5, (0.9, 0.95, 1.0), 20),
    "M_City_Building": ((0.03, 0.035, 0.05), 0.6, 0.25, None, 0),
    "M_City_Ground": ((0.008, 0.008, 0.012), 0.0, 0.8, None, 0),
    "M_City_BeaconRed": ((1.0, 0.05, 0.02), 0.0, 0.5, (1.0, 0.05, 0.02), 40),
    "M_City_NeonCyan": ((0.0, 0.8, 1.0), 0.0, 0.5, (0.0, 0.8, 1.0), 20),
    "M_City_NeonMagenta": ((1.0, 0.1, 0.7), 0.0, 0.5, (1.0, 0.1, 0.7), 20),
    "M_City_NeonPurple": ((0.5, 0.15, 1.0), 0.0, 0.5, (0.5, 0.15, 1.0), 20),
    "M_City_NeonAmber": ((1.0, 0.45, 0.05), 0.0, 0.5, (1.0, 0.45, 0.05), 20),
}

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
BEL = unreal.BlueprintEditorLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    unreal.log("SPACECITY " + msg)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def try_set(obj, names, value):
    """Set the first property name that exists (names differ between engine versions)."""
    for n in names:
        try:
            obj.set_editor_property(n, value)
            return n
        except Exception:
            continue
    log("  (could not set any of", names, ")")
    return None


# ---------------------------------------------------------------- 1. materials
def build_material(name, base, metallic, rough, emit, strength):
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
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat, only_if_is_dirty=False)
    return mat


# ---------------------------------------------------------------- 2. meshes
def import_meshes(materials, names):
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")
    meshes = {}
    for name in names:
        ui = unreal.FbxImportUI()
        ui.set_editor_property("import_mesh", True)
        ui.set_editor_property("import_as_skeletal", False)
        ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        ui.set_editor_property("import_materials", False)
        ui.set_editor_property("import_textures", False)
        ui.set_editor_property("import_animations", False)
        sd = ui.static_mesh_import_data
        sd.set_editor_property("combine_meshes", True)
        sd.set_editor_property("generate_lightmap_u_vs", False)
        sd.set_editor_property("auto_generate_collision", True)
        sd.set_editor_property("remove_degenerates", True)

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", os.path.join(EXPORT_DIR, name + ".fbx"))
        task.set_editor_property("destination_path", f"{BASE}/Meshes")
        task.set_editor_property("destination_name", name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", True)
        task.set_editor_property("options", ui)
        AT.import_asset_tasks([task])

        mesh = EAL.load_asset(f"{BASE}/Meshes/{name}")
        if not mesh:
            raise RuntimeError(f"import failed: {name}")
        slots = mesh.get_editor_property("static_materials")
        missing = []
        for s in slots:
            slot = str(s.get_editor_property("material_slot_name"))
            mat = materials.get(slot) or materials.get(str(s.get_editor_property("imported_material_slot_name")))
            if mat:
                s.set_editor_property("material_interface", mat)
            else:
                missing.append(slot)
        mesh.set_editor_property("static_materials", slots)

        # Drive on the real triangles, not a rough hull
        body = mesh.get_editor_property("body_setup")
        if body:
            body.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
        EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
        meshes[name] = mesh
        log(f"mesh {name}: {len(slots)} slots{' MISSING ' + str(missing) if missing else ''}, "
            f"collision={'complex' if body else 'NONE'}")
    return meshes


# ---------------------------------------------------------------- 3. level
def build_level(meshes, info):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if EAL.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
        for a in eas.get_all_level_actors():
            if not isinstance(a, unreal.WorldSettings):
                eas.destroy_actor(a)
        log("level: reusing", LEVEL)
    else:
        if not les.new_level(LEVEL):
            raise RuntimeError("could not create level " + LEVEL)
        log("level: created", LEVEL)

    def spawn_class(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
        a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2]))
        if not a:
            raise RuntimeError(f"could not spawn {label} ({cls.__name__})")
        a.set_actor_label(label)
        return a

    # City + track meshes, all authored around the world origin
    for name, mesh in meshes.items():
        a = spawn_class(unreal.StaticMeshActor, name.replace("SM_", ""))
        a.get_editor_property("static_mesh_component").set_static_mesh(mesh)

    # Night lighting
    moon = spawn_class(unreal.DirectionalLight, "Moon", rot=(0, -40, 35))
    lc = moon.get_editor_property("light_component")
    lc.set_editor_property("intensity", 0.12)
    lc.set_editor_property("light_color", unreal.Color(r=150, g=175, b=255, a=255))

    sky = spawn_class(unreal.SkyLight, "SkyLight", loc=(0, 0, 2000))
    sc = sky.get_editor_property("light_component")
    sc.set_editor_property("intensity", 0.15)
    try_set(sc, ["lower_hemisphere_color"], unreal.LinearColor(0.01, 0.005, 0.03, 1))

    fog = spawn_class(unreal.ExponentialHeightFog, "NightFog", loc=(0, 0, 0))
    fc = fog.get_editor_property("component")
    # Thin haze only: thick fog washes out the neon on the towers
    fc.set_editor_property("fog_density", 0.0004)
    fc.set_editor_property("fog_height_falloff", 0.05)
    try_set(fc, ["fog_inscattering_luminance", "fog_inscattering_color"], unreal.LinearColor(0.008, 0.003, 0.02, 1))
    try_set(fc, ["volumetric_fog"], True)

    ppv = spawn_class(unreal.PostProcessVolume, "NightLook")
    ppv.set_editor_property("unbound", True)
    s = ppv.get_editor_property("settings")
    for flag, prop, value in (
        # Locked exposure (EV100): stops the camera brightening the night until the neon washes out
        ("override_auto_exposure_min_brightness", "auto_exposure_min_brightness", 0.0),
        ("override_auto_exposure_max_brightness", "auto_exposure_max_brightness", 0.0),
        ("override_bloom_intensity", "bloom_intensity", 1.2),
    ):
        try:
            s.set_editor_property(flag, True)
            s.set_editor_property(prop, value)
        except Exception as exc:
            log("  post-process setting skipped:", prop, exc)
    ppv.set_editor_property("settings", s)

    # Start on the grid
    x, y, z = info["start_location_cm"]
    spawn_class(unreal.PlayerStart, "Start", loc=(x, y, z), rot=(0, 0, info["start_yaw_deg"]))

    # Use the vehicle game mode (spawns BP_SpaceCar)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    gm = BEL.generated_class(EAL.load_asset(GAME_MODE))
    world.get_world_settings().set_editor_property("default_game_mode", gm)

    if not les.save_current_level():
        raise RuntimeError("could not save level")
    log("level saved with", len(eas.get_all_level_actors()), "actors")


# ---------------------------------------------------------------- 4. default map
def set_default_map():
    ini = os.path.join(PROJECT_DIR, "Config", "DefaultEngine.ini")
    with open(ini, encoding="utf-8") as f:
        text = f.read()
    ref = f"{LEVEL}.{LEVEL.split('/')[-1]}"
    for key in ("GameDefaultMap", "EditorStartupMap"):
        text = re.sub(rf"^{key}=.*$", f"{key}={ref}", text, flags=re.M)
    with open(ini, "w", encoding="utf-8") as f:
        f.write(text)
    log("default map:", ref)


def main():
    with open(os.path.join(EXPORT_DIR, "track_info.json"), encoding="utf-8") as f:
        info = json.load(f)
    log("track:", info["track_length_m"], "m, start", info["start_location_cm"], "yaw", info["start_yaw_deg"])
    materials = {name: build_material(name, *spec) for name, spec in MATERIALS.items()}
    log("materials:", len(materials))
    meshes = import_meshes(materials, info["meshes"])
    build_level(meshes, info)
    set_default_map()
    log("DONE")


main()
