"""Read-only: report what Lvl_SpaceCity contains (actors, start spot, game mode)."""
import os

import unreal

OUT = os.environ.get("SCR_LOG", "")


def log(*parts):
    msg = " ".join(str(p) for p in parts)
    unreal.log("SPACECITY " + msg)
    if OUT:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


world = unreal.EditorLoadingAndSavingUtils.load_map("/Game/SpaceCity/Maps/Lvl_SpaceCity")
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    extra = ""
    if isinstance(a, unreal.StaticMeshActor):
        extra = f" mesh={a.get_editor_property('static_mesh_component').get_editor_property('static_mesh').get_name()}"
    log(f"{a.get_actor_label():28s} {a.get_class().get_name():26s} loc={a.get_actor_location()} rot={a.get_actor_rotation()}{extra}")
ws = world.get_world_settings()
log("game mode override:", ws.get_editor_property("default_game_mode"))
log("kill z:", ws.get_editor_property("kill_z"))
