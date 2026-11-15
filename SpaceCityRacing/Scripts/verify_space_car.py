"""Read-only check that the space car setup is saved correctly on disk."""
import os

import unreal

OUT = os.environ.get("SCR_LOG", "")
EAL = unreal.EditorAssetLibrary
BEL = unreal.BlueprintEditorLibrary
SDL = unreal.SubobjectDataBlueprintFunctionLibrary


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    unreal.log("SPACECAR " + msg)
    if OUT:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


bp = EAL.load_asset("/Game/SpaceCar/Blueprints/BP_SpaceCar")
cdo = unreal.get_default_object(BEL.generated_class(bp))
log("mesh:", cdo.get_editor_property("mesh").get_editor_property("skeletal_mesh_asset").get_name(),
    "visible:", cdo.get_editor_property("mesh").get_editor_property("visible"))
for w in cdo.get_editor_property("vehicle_movement_component").get_editor_property("wheel_setups"):
    wc = unreal.get_default_object(w.get_editor_property("wheel_class"))
    log("wheel:", w.get_editor_property("bone_name"), w.get_editor_property("wheel_class").get_name(),
        "radius", wc.get_editor_property("wheel_radius"), "width", wc.get_editor_property("wheel_width"))

sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
for h in sds.k2_gather_subobject_data_for_blueprint(bp):
    d = SDL.get_data(h)
    obj = SDL.get_object(d)
    if isinstance(obj, unreal.StaticMeshComponent):
        log("static part:", SDL.get_variable_name(d), "mesh:", obj.get_editor_property("static_mesh"))

gm = unreal.get_default_object(BEL.generated_class(EAL.load_asset("/Game/VehicleTemplate/Blueprints/BP_VehicleAdvGameMode")))
log("default pawn:", gm.get_editor_property("default_pawn_class").get_name())
mesh = EAL.load_asset("/Game/SpaceCar/Meshes/SK_SpaceCar")
log("mesh physics asset:", mesh.get_editor_property("physics_asset").get_name())
log("mesh materials:", [(s.get_editor_property("material_interface").get_name(),
                         "skeletal-ok" if s.get_editor_property("material_interface").get_editor_property("used_with_skeletal_mesh") else "NOT FLAGGED")
                        for s in mesh.get_editor_property("materials")])
