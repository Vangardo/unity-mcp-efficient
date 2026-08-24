"""Dynamic operation-level catalog for the efficient Unity MCP facade."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import log
from typing import Any

from mcp.types import Tool

_EXCLUDED_TOOLS = {"batch_execute", "manage_tools", "debug_request_context"}

# Some upstream tools intentionally use an open string for ``action``. Keeping
# the known stable actions here makes them individually discoverable without
# copying the enormous tool description into every model request.
_KNOWN_ACTIONS: dict[str, tuple[str, ...]] = {
    "manage_animation": (
        "animator_get_info",
        "animator_get_parameter",
        "animator_play",
        "animator_crossfade",
        "animator_set_parameter",
        "animator_set_speed",
        "animator_set_enabled",
        "controller_create",
        "controller_add_state",
        "controller_add_transition",
        "controller_add_parameter",
        "controller_get_info",
        "controller_assign",
        "controller_add_layer",
        "controller_remove_layer",
        "controller_set_layer_weight",
        "controller_create_blend_tree_1d",
        "controller_create_blend_tree_2d",
        "controller_add_blend_tree_child",
        "clip_create",
        "clip_get_info",
        "clip_add_curve",
        "clip_set_curve",
        "clip_set_vector_curve",
        "clip_create_preset",
        "clip_assign",
        "clip_add_event",
        "clip_remove_event",
    ),
    "manage_build": (
        "build",
        "status",
        "platform",
        "settings",
        "scenes",
        "profiles",
        "batch",
        "cancel",
    ),
    "manage_camera": (
        "ping",
        "ensure_brain",
        "get_brain_status",
        "create_camera",
        "set_target",
        "set_priority",
        "set_lens",
        "set_body",
        "set_aim",
        "set_noise",
        "add_extension",
        "remove_extension",
        "set_blend",
        "force_camera",
        "release_override",
        "list_cameras",
        "screenshot",
        "screenshot_multiview",
    ),
    "manage_graphics": (
        "ping",
        "volume_create",
        "volume_add_effect",
        "volume_set_effect",
        "volume_remove_effect",
        "volume_get_info",
        "volume_set_properties",
        "volume_list_effects",
        "volume_create_profile",
        "bake_start",
        "bake_cancel",
        "bake_status",
        "bake_clear",
        "bake_reflection_probe",
        "bake_get_settings",
        "bake_set_settings",
        "bake_create_light_probe_group",
        "bake_create_reflection_probe",
        "bake_set_probe_positions",
        "stats_get",
        "stats_list_counters",
        "stats_set_scene_debug",
        "stats_get_memory",
        "pipeline_get_info",
        "pipeline_set_quality",
        "pipeline_get_settings",
        "pipeline_set_settings",
        "feature_list",
        "feature_add",
        "feature_remove",
        "feature_configure",
        "feature_toggle",
        "feature_reorder",
        "skybox_get",
        "skybox_set_material",
        "skybox_set_properties",
        "skybox_set_ambient",
        "skybox_set_fog",
        "skybox_set_reflection",
        "skybox_set_sun",
    ),
    "manage_packages": (
        "list_packages",
        "search_packages",
        "get_package_info",
        "ping",
        "status",
        "add_package",
        "remove_package",
        "list_registries",
        "add_registry",
        "remove_registry",
        "embed_package",
        "resolve_packages",
    ),
    "manage_profiler": (
        "profiler_start",
        "profiler_stop",
        "profiler_status",
        "profiler_set_areas",
        "get_frame_timing",
        "get_counters",
        "get_object_memory",
        "memory_take_snapshot",
        "memory_list_snapshots",
        "memory_compare_snapshots",
        "frame_debugger_enable",
        "frame_debugger_disable",
        "frame_debugger_get_events",
    ),
    "manage_probuilder": (
        "create_shape",
        "create_poly_shape",
        "extrude_faces",
        "extrude_edges",
        "bevel_edges",
        "subdivide",
        "delete_faces",
        "bridge_edges",
        "connect_elements",
        "detach_faces",
        "flip_normals",
        "merge_faces",
        "combine_meshes",
        "merge_objects",
        "duplicate_and_flip",
        "create_polygon",
        "merge_vertices",
        "weld_vertices",
        "split_vertices",
        "move_vertices",
        "insert_vertex",
        "append_vertices_to_edge",
        "select_faces",
        "set_face_material",
        "set_face_color",
        "set_face_uvs",
        "get_mesh_info",
        "convert_to_probuilder",
        "set_smoothing",
        "auto_smooth",
        "center_pivot",
        "set_pivot",
        "freeze_transform",
        "validate_mesh",
        "repair_mesh",
    ),
    "manage_vfx": (
        "ping",
        "particle_create",
        "particle_get_info",
        "particle_set_main",
        "particle_set_emission",
        "particle_set_shape",
        "particle_set_color_over_lifetime",
        "particle_set_size_over_lifetime",
        "particle_set_velocity_over_lifetime",
        "particle_set_noise",
        "particle_set_renderer",
        "particle_enable_module",
        "particle_play",
        "particle_stop",
        "particle_pause",
        "particle_restart",
        "particle_clear",
        "particle_add_burst",
        "particle_clear_bursts",
        "vfx_create_asset",
        "vfx_assign_asset",
        "vfx_list_templates",
        "vfx_list_assets",
        "vfx_get_info",
        "vfx_set_float",
        "vfx_set_int",
        "vfx_set_bool",
        "vfx_set_vector2",
        "vfx_set_vector3",
        "vfx_set_vector4",
        "vfx_set_color",
        "vfx_set_gradient",
        "vfx_set_texture",
        "vfx_set_mesh",
        "vfx_set_curve",
        "vfx_send_event",
        "vfx_play",
        "vfx_stop",
        "vfx_pause",
        "vfx_reinit",
        "vfx_set_playback_speed",
        "vfx_set_seed",
        "line_get_info",
        "line_set_positions",
        "line_add_position",
        "line_set_position",
        "line_set_width",
        "line_set_color",
        "line_set_material",
        "line_set_properties",
        "line_clear",
        "line_create_line",
        "line_create_circle",
        "line_create_arc",
        "line_create_bezier",
        "trail_get_info",
        "trail_set_time",
        "trail_set_width",
        "trail_set_color",
        "trail_set_material",
        "trail_set_properties",
        "trail_clear",
        "trail_emit",
    ),
    "unity_docs": ("get_doc", "get_manual", "get_package_doc", "lookup"),
    "unity_reflect": ("get_type", "get_member", "search"),
}

_DIRECT_NAMES = {
    "apply_text_edits": "script.apply_text_edits",
    "create_script": "script.create",
    "delete_script": "script.delete",
    "execute_code": "code.execute",
    "execute_custom_tool": "custom.execute",
    "execute_menu_item": "editor.menu",
    "find_gameobjects": "gameobject.find",
    "find_in_file": "script.find",
    "get_sha": "script.sha",
    "get_test_job": "tests.result",
    "import_model": "asset.import_generated_model",
    "import_model_file": "asset.import_model_file",
    "refresh_unity": "editor.refresh",
    "run_tests": "tests.run",
    "script_apply_edits": "script.apply_edits",
    "set_active_instance": "system.set_instance",
    "unity_docs": "docs.lookup",
    "unity_reflect": "docs.reflect",
    "validate_script": "script.validate",
}

_OPERATION_NAME_OVERRIDES = {
    ("import_model", "search"): "asset.generated_model_search",
    ("import_model", "preview"): "asset.generated_model_preview",
    ("import_model", "import"): "asset.import_generated_model",
    ("import_model", "status"): "asset.generated_model_status",
    ("import_model", "cancel"): "asset.generated_model_cancel",
    ("import_model", "list_providers"): "asset.generated_model_providers",
    ("manage_asset", "search"): "asset.search",
}

_TOOL_CATEGORIES = {
    "manage_animation": "animation",
    "manage_asset": "asset",
    "manage_build": "build",
    "manage_camera": "camera",
    "manage_components": "component",
    "manage_editor": "editor",
    "manage_gameobject": "gameobject",
    "manage_graphics": "graphics",
    "manage_material": "material",
    "manage_packages": "package",
    "manage_physics": "physics",
    "manage_prefabs": "prefab",
    "manage_probuilder": "probuilder",
    "manage_profiler": "profiler",
    "manage_scene": "scene",
    "manage_script": "script",
    "manage_script_capabilities": "script",
    "manage_scriptable_object": "scriptable_object",
    "manage_shader": "shader",
    "manage_texture": "texture",
    "manage_ui": "ui",
    "manage_vfx": "vfx",
    "read_console": "console",
    "generate_audio": "asset",
    "generate_image": "asset",
    "generate_model": "asset",
}

_ALIASES = {
    "editor.refresh": "refresh asset database compile scripts reimport domain reload",
    "editor.play": "enter start play mode run game",
    "editor.pause": "pause play mode game",
    "editor.stop": "exit leave stop play mode game",
    "scene.get_hierarchy": "scene tree roots children objects overview inspect hierarchy",
    "scene.get_active": "current active scene status",
    "gameobject.create": "create spawn primitive cube sphere object prefab instantiate",
    "gameobject.modify": "move rotate scale rename activate tag layer object",
    "gameobject.find": "search locate object name tag component path",
    "component.add": "attach add component behavior rigidbody collider script",
    "component.set_property": "configure component fields properties values references",
    "console.get": "errors warnings logs compilation diagnostics stack trace",
    "script.create": "write new csharp mono behaviour code",
    "script.apply_edits": "edit patch csharp method class code",
    "script.validate": "compile syntax semantic diagnostics csharp",
    "code.execute": "run ad hoc csharp prototype automate editor",
    "asset.search": "find project assets prefab material texture script shader",
    "camera.screenshot": "capture viewport scene view game view image verify",
    "camera.screenshot_multiview": "capture surround contact sheet multiple angles",
    "tests.run": "run editmode playmode unit tests",
    "tests.result": "poll wait test job failures",
    "docs.reflect": "verify unity api type member signature reflection",
    "docs.lookup": "official unity documentation manual package api",
    "probuilder.get_mesh_info": "mesh summary faces edges bounds topology",
    "probuilder.create_shape": "create spawn primitive cube cylinder sphere cone torus stairs mesh",
    "probuilder.extrude_faces": "model push pull extrude selected faces geometry",
    "probuilder.bevel_edges": "model bevel chamfer selected edges geometry",
    "profiler.get_frame_timing": "performance fps cpu gpu frame timing",
    "asset.generate_image.generate": "generate create image texture sprite",
    "asset.generate_model.generate": "generate create 3d model mesh",
    "asset.generate_audio.generate": "generate create audio sound music",
    "vfx.particle_create": "create particle system fire smoke sparks effect",
}

_OPERATION_PARAMETER_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "asset.search": (
        "path",
        "generate_preview",
        "search_pattern",
        "filter_type",
        "filter_date_after",
        "page_size",
        "page_number",
    ),
    "editor.play": (),
    "editor.pause": (),
    "editor.stop": (),
    "editor.undo": (),
    "editor.redo": (),
    "editor.telemetry_status": (),
    "editor.telemetry_ping": (),
    "editor.set_active_tool": ("tool_name",),
    "editor.add_tag": ("tag_name",),
    "editor.remove_tag": ("tag_name",),
    "editor.add_layer": ("layer_name",),
    "editor.remove_layer": ("layer_name",),
}

# Universal upstream managers expose the union of every action parameter.  The
# facade narrows that union after the action is known, so the model never has to
# read (or choose between) unrelated fields.  Missing entries intentionally fall
# back to the full upstream schema: an incomplete contract is worse than a few
# extra tokens.
_TOOL_ACTION_PARAMETER_ALLOWLIST: dict[tuple[str, str], tuple[str, ...]] = {
    ("manage_gameobject", "create"): (
        "name",
        "tag",
        "parent",
        "position",
        "rotation",
        "scale",
        "components_to_add",
        "primitive_type",
        "save_as_prefab",
        "prefab_path",
        "prefab_folder",
        "set_active",
        "layer",
        "is_static",
    ),
    ("manage_gameobject", "modify"): (
        "target",
        "search_method",
        "new_name",
        "tag",
        "parent",
        "position",
        "rotation",
        "scale",
        "set_active",
        "layer",
        "is_static",
        "components_to_add",
        "components_to_remove",
        "component_properties",
    ),
    ("manage_gameobject", "delete"): ("target", "search_method"),
    ("manage_gameobject", "duplicate"): (
        "target",
        "search_method",
        "new_name",
        "parent",
        "position",
        "rotation",
        "scale",
    ),
    ("manage_gameobject", "move_relative"): (
        "target",
        "search_method",
        "offset",
        "reference_object",
        "direction",
        "distance",
        "world_space",
    ),
    ("manage_gameobject", "look_at"): (
        "target",
        "search_method",
        "look_at_target",
        "look_at_up",
    ),
    ("manage_scene", "get_hierarchy"): (
        "parent",
        "page_size",
        "cursor",
        "max_nodes",
        "max_depth",
        "max_children_per_node",
        "include_transform",
    ),
    ("manage_scene", "get_active"): (),
    ("manage_scene", "get_build_settings"): (),
    ("manage_scene", "get_loaded_scenes"): (),
    ("manage_scene", "scene_view_frame"): ("scene_view_target",),
    ("manage_scene", "create"): ("name", "path", "template"),
    ("manage_scene", "load"): ("path", "build_index", "additive"),
    ("manage_scene", "save"): ("name", "path", "scene_name", "scene_path"),
    ("manage_scene", "close_scene"): (
        "scene_name",
        "scene_path",
        "remove_scene",
    ),
    ("manage_scene", "set_active_scene"): ("scene_name", "scene_path"),
    ("manage_scene", "move_to_scene"): (
        "target",
        "scene_name",
        "scene_path",
    ),
    ("manage_scene", "validate"): (
        "scene_name",
        "scene_path",
        "auto_repair",
    ),
    ("manage_physics", "ping"): ("dimension",),
    ("manage_physics", "get_settings"): ("dimension",),
    ("manage_physics", "set_settings"): ("dimension", "settings"),
    ("manage_physics", "get_collision_matrix"): (
        "dimension",
        "layer_a",
        "layer_b",
        "page_size",
        "cursor",
    ),
    ("manage_physics", "set_collision_matrix"): (
        "dimension",
        "layer_a",
        "layer_b",
        "collide",
    ),
    ("manage_physics", "create_physics_material"): (
        "name",
        "path",
        "dynamic_friction",
        "static_friction",
        "bounciness",
        "friction",
        "friction_combine",
        "bounce_combine",
    ),
    ("manage_physics", "configure_physics_material"): (
        "material_path",
        "dynamic_friction",
        "static_friction",
        "bounciness",
        "friction",
        "friction_combine",
        "bounce_combine",
    ),
    ("manage_physics", "assign_physics_material"): (
        "target",
        "search_method",
        "collider_type",
        "component_index",
        "material_path",
    ),
    ("manage_physics", "add_joint"): (
        "dimension",
        "target",
        "search_method",
        "joint_type",
        "connected_body",
        "motor",
        "limits",
        "spring",
        "drive",
        "properties",
        "component_index",
    ),
    ("manage_physics", "configure_joint"): (
        "dimension",
        "target",
        "search_method",
        "joint_type",
        "connected_body",
        "motor",
        "limits",
        "spring",
        "drive",
        "properties",
        "component_index",
    ),
    ("manage_physics", "remove_joint"): (
        "dimension",
        "target",
        "search_method",
        "joint_type",
        "component_index",
    ),
    ("manage_physics", "raycast"): (
        "dimension",
        "origin",
        "direction",
        "max_distance",
        "layer_mask",
        "query_trigger_interaction",
    ),
    ("manage_physics", "raycast_all"): (
        "dimension",
        "origin",
        "direction",
        "max_distance",
        "layer_mask",
        "query_trigger_interaction",
        "page_size",
        "cursor",
    ),
    ("manage_physics", "linecast"): (
        "dimension",
        "start",
        "end",
        "layer_mask",
        "query_trigger_interaction",
    ),
    ("manage_physics", "shapecast"): (
        "dimension",
        "shape",
        "origin",
        "direction",
        "max_distance",
        "position",
        "size",
        "point1",
        "point2",
        "height",
        "capsule_direction",
        "angle",
        "layer_mask",
        "query_trigger_interaction",
        "page_size",
        "cursor",
    ),
    ("manage_physics", "overlap"): (
        "dimension",
        "shape",
        "position",
        "size",
        "point1",
        "point2",
        "height",
        "capsule_direction",
        "angle",
        "layer_mask",
        "query_trigger_interaction",
        "page_size",
        "cursor",
    ),
    ("manage_physics", "apply_force"): (
        "dimension",
        "target",
        "search_method",
        "force",
        "force_mode",
        "force_type",
        "torque",
        "explosion_position",
        "explosion_radius",
        "explosion_force",
        "upwards_modifier",
        "component_index",
    ),
    ("manage_physics", "get_rigidbody"): (
        "dimension",
        "target",
        "search_method",
        "component_index",
    ),
    ("manage_physics", "configure_rigidbody"): (
        "dimension",
        "target",
        "search_method",
        "properties",
        "component_index",
    ),
    ("manage_physics", "validate"): (
        "dimension",
        "target",
        "search_method",
        "page_size",
        "cursor",
    ),
    ("manage_physics", "simulate_step"): (
        "dimension",
        "steps",
        "step_size",
    ),
}

_GRAPHICS_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "ping": (),
    "volume_create": (
        "name",
        "is_global",
        "weight",
        "priority",
        "profile_path",
        "effects",
    ),
    "volume_add_effect": ("target", "effect"),
    "volume_set_effect": ("target", "effect", "parameters"),
    "volume_remove_effect": ("target", "effect"),
    "volume_get_info": ("target",),
    "volume_set_properties": (
        "target",
        "properties",
        "is_global",
        "weight",
        "priority",
    ),
    "volume_list_effects": (),
    "volume_create_profile": ("path", "name"),
    "bake_start": ("async_bake",),
    "bake_cancel": (),
    "bake_status": (),
    "bake_clear": (),
    "bake_reflection_probe": ("target",),
    "bake_get_settings": (),
    "bake_set_settings": ("settings",),
    "bake_create_light_probe_group": (
        "name",
        "position",
        "grid_size",
        "spacing",
    ),
    "bake_create_reflection_probe": (
        "name",
        "position",
        "size",
        "resolution",
        "mode",
        "hdr",
        "box_projection",
    ),
    "bake_set_probe_positions": ("target", "positions"),
    "stats_get": (),
    "stats_list_counters": (),
    "stats_set_scene_debug": ("mode",),
    "stats_get_memory": (),
    "pipeline_get_info": (),
    "pipeline_set_quality": ("level",),
    "pipeline_get_settings": (),
    "pipeline_set_settings": ("settings",),
    "feature_list": (),
    "feature_add": ("feature_type", "name", "material", "properties"),
    "feature_remove": ("index", "name"),
    "feature_configure": ("index", "name", "properties"),
    "feature_toggle": ("index", "name", "active"),
    "feature_reorder": ("order",),
    "skybox_get": (),
    "skybox_set_material": ("material",),
    "skybox_set_properties": ("properties",),
    "skybox_set_ambient": (
        "ambient_mode",
        "intensity",
        "color",
        "equator_color",
        "ground_color",
    ),
    "skybox_set_fog": (
        "fog_enabled",
        "fog_mode",
        "fog_color",
        "fog_density",
        "fog_start",
        "fog_end",
    ),
    "skybox_set_reflection": (
        "intensity",
        "bounces",
        "reflection_mode",
        "resolution",
        "material",
    ),
    "skybox_set_sun": ("target",),
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_graphics", action): parameters
        for action, parameters in _GRAPHICS_ACTION_PARAMETERS.items()
    }
)

_UI_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "ping": (),
    "create": ("path", "contents"),
    "read": ("path",),
    "update": ("path", "contents"),
    "delete": ("path",),
    "attach_ui_document": (
        "target",
        "source_asset",
        "panel_settings",
        "sort_order",
    ),
    "detach_ui_document": ("target",),
    "create_panel_settings": (
        "path",
        "settings",
        "scale_mode",
        "reference_resolution",
    ),
    "update_panel_settings": ("path", "panel_settings", "settings"),
    "get_visual_tree": ("target", "max_depth"),
    "render_ui": (
        "target",
        "path",
        "width",
        "height",
        "include_image",
        "max_resolution",
        "screenshot_file_name",
        "output_folder",
    ),
    "link_stylesheet": ("path", "stylesheet"),
    "list": ("filter_type", "page_size", "page_number"),
    "modify_visual_element": (
        "target",
        "element_name",
        "text",
        "add_classes",
        "remove_classes",
        "toggle_classes",
        "style",
        "enabled",
        "visible",
        "tooltip",
    ),
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_ui", action): parameters
        for action, parameters in _UI_ACTION_PARAMETERS.items()
    }
)

_CAMERA_CAPTURE_PARAMETERS = (
    "screenshot_file_name",
    "screenshot_super_size",
    "camera",
    "include_image",
    "max_resolution",
    "capture_source",
    "batch",
    "view_target",
    "view_position",
    "view_rotation",
    "orbit_angles",
    "orbit_elevations",
    "orbit_distance",
    "orbit_fov",
    "output_folder",
)
_CAMERA_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "ping": (),
    "ensure_brain": ("target", "search_method"),
    "get_brain_status": (),
    "create_camera": ("target", "properties"),
    "set_target": ("target", "search_method", "properties"),
    "set_priority": ("target", "search_method", "properties"),
    "set_lens": ("target", "search_method", "properties"),
    "set_body": ("target", "search_method", "properties"),
    "set_aim": ("target", "search_method", "properties"),
    "set_noise": ("target", "search_method", "properties"),
    "add_extension": ("target", "search_method", "properties"),
    "remove_extension": ("target", "search_method", "properties"),
    "set_blend": ("properties",),
    "force_camera": ("target", "search_method"),
    "release_override": (),
    "list_cameras": (),
    "screenshot": _CAMERA_CAPTURE_PARAMETERS,
    "screenshot_multiview": _CAMERA_CAPTURE_PARAMETERS,
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_camera", action): parameters
        for action, parameters in _CAMERA_ACTION_PARAMETERS.items()
    }
)

_PREFAB_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "create_from_gameobject": (
        "target",
        "prefab_path",
        "allow_overwrite",
        "unlink_if_instance",
    ),
    "get_info": ("prefab_path",),
    "get_hierarchy": ("prefab_path",),
    "modify_contents": (
        "prefab_path",
        "target",
        "search_inactive",
        "position",
        "rotation",
        "scale",
        "name",
        "tag",
        "layer",
        "set_active",
        "parent",
        "components_to_add",
        "components_to_remove",
        "create_child",
        "delete_child",
        "component_properties",
    ),
    "open_prefab_stage": ("prefab_path",),
    "save_prefab_stage": (),
    "close_prefab_stage": (),
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_prefabs", action): parameters
        for action, parameters in _PREFAB_ACTION_PARAMETERS.items()
    }
)

_TEXTURE_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "create": (
        "path",
        "width",
        "height",
        "fill_color",
        "pattern",
        "palette",
        "pattern_size",
        "pixels",
        "image_path",
        "as_sprite",
        "import_settings",
    ),
    "modify": ("path", "set_pixels"),
    "delete": ("path",),
    "create_sprite": (
        "path",
        "width",
        "height",
        "fill_color",
        "pixels",
        "image_path",
        "as_sprite",
        "import_settings",
    ),
    "apply_pattern": ("path", "pattern", "palette", "pattern_size"),
    "apply_gradient": (
        "path",
        "palette",
        "gradient_type",
        "gradient_angle",
    ),
    "apply_noise": ("path", "palette", "noise_scale", "octaves"),
    "set_import_settings": ("path", "import_settings"),
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_texture", action): parameters
        for action, parameters in _TEXTURE_ACTION_PARAMETERS.items()
    }
)

_BUILD_ACTION_PARAMETERS: dict[str, tuple[str, ...]] = {
    "build": (
        "target",
        "output_path",
        "scenes",
        "development",
        "options",
        "subtarget",
        "scripting_backend",
        "profile",
    ),
    "status": ("job_id",),
    "platform": ("target",),
    "settings": ("property", "value", "target"),
    "scenes": ("scenes",),
    "profiles": ("profile", "activate"),
    "batch": (
        "targets",
        "profiles",
        "output_dir",
        "scenes",
        "development",
        "options",
        "subtarget",
        "scripting_backend",
    ),
    "cancel": ("job_id",),
}
_TOOL_ACTION_PARAMETER_ALLOWLIST.update(
    {
        ("manage_build", action): parameters
        for action, parameters in _BUILD_ACTION_PARAMETERS.items()
    }
)

_ACTION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "gameobject.modify": ("target",),
    "gameobject.delete": ("target",),
    "gameobject.duplicate": ("target",),
    "gameobject.move_relative": ("target",),
    "gameobject.look_at": ("target", "look_at_target"),
    "physics.raycast": ("origin", "direction"),
    "physics.raycast_all": ("origin", "direction"),
    "physics.linecast": ("start", "end"),
    "physics.apply_force": ("target", "force"),
    "physics.configure_rigidbody": ("target", "properties"),
    "physics.get_rigidbody": ("target",),
    "graphics.volume_add_effect": ("target", "effect"),
    "graphics.volume_set_effect": ("target", "effect", "parameters"),
    "graphics.volume_remove_effect": ("target", "effect"),
    "graphics.volume_get_info": ("target",),
    "graphics.volume_set_properties": ("target",),
    "graphics.bake_reflection_probe": ("target",),
    "graphics.bake_set_settings": ("settings",),
    "graphics.bake_set_probe_positions": ("target", "positions"),
    "graphics.pipeline_set_quality": ("level",),
    "graphics.pipeline_set_settings": ("settings",),
    "graphics.skybox_set_material": ("material",),
    "graphics.skybox_set_properties": ("properties",),
    "graphics.skybox_set_sun": ("target",),
    "ui.create": ("path", "contents"),
    "ui.read": ("path",),
    "ui.update": ("path", "contents"),
    "ui.delete": ("path",),
    "ui.attach_ui_document": ("target", "source_asset"),
    "ui.detach_ui_document": ("target",),
    "ui.get_visual_tree": ("target",),
    "ui.link_stylesheet": ("path", "stylesheet"),
    "ui.modify_visual_element": ("target", "element_name"),
    "camera.set_target": ("target", "properties"),
    "camera.set_priority": ("target", "properties"),
    "camera.set_lens": ("target", "properties"),
    "camera.set_body": ("target", "properties"),
    "camera.set_aim": ("target", "properties"),
    "camera.set_noise": ("target", "properties"),
    "camera.add_extension": ("target", "properties"),
    "camera.remove_extension": ("target", "properties"),
    "camera.force_camera": ("target",),
    "prefab.create_from_gameobject": ("target", "prefab_path"),
    "prefab.get_info": ("prefab_path",),
    "prefab.get_hierarchy": ("prefab_path",),
    "prefab.modify_contents": ("prefab_path",),
    "prefab.open_prefab_stage": ("prefab_path",),
    "texture.create": ("path",),
    "texture.modify": ("path", "set_pixels"),
    "texture.delete": ("path",),
    "texture.create_sprite": ("path",),
    "texture.apply_pattern": ("path", "pattern"),
    "texture.apply_gradient": ("path", "palette"),
    "texture.apply_noise": ("path",),
    "texture.set_import_settings": ("path", "import_settings"),
}

_EXAMPLES: dict[str, dict[str, Any]] = {
    "gameobject.create": {
        "name": "Crate",
        "primitive_type": "Cube",
        "position": [0, 0.5, 0],
    },
    "gameobject.modify": {"target": "Crate", "position": [0, 1, 0]},
    "physics.raycast": {
        "origin": [0, 10, 0],
        "direction": [0, -1, 0],
        "max_distance": 100,
    },
    "scene.get_hierarchy": {"max_depth": 3, "max_nodes": 80},
    "tests.run": {"mode": "EditMode"},
}

_SPECIALIZED_CATEGORY_TERMS: dict[str, set[str]] = {
    "animation": {
        "animation",
        "animator",
        "blend",
        "clip",
        "controller",
        "crossfade",
    },
    "probuilder": {
        "bevel",
        "edge",
        "face",
        "geometry",
        "mesh",
        "model",
        "modeling",
        "polygon",
        "probuilder",
        "topology",
        "vertex",
    },
    "vfx": {
        "effect",
        "fire",
        "line",
        "particle",
        "smoke",
        "spark",
        "trail",
        "vfx",
        "visual",
    },
}

_GUIDANCE = {
    "vfx.particle_create": "Create or prepare a ParticleSystem on target; renderer material is assigned automatically when omitted.",
    "vfx.particle_set_main": "Set duration, looping, startLifetime, startSpeed, startSize, startColor, gravityModifier, maxParticles, simulationSpace, or playOnAwake in properties.",
    "vfx.particle_set_emission": "Set rateOverTime or rateOverDistance in properties.",
    "vfx.particle_set_shape": "Set shapeType, radius, angle, arc, position, rotation, or scale in properties.",
    "vfx.line_create_line": "Create a line with start, end, and optional segments in properties.",
    "vfx.line_create_circle": "Create a circle with center, radius, segments, and optional normal in properties.",
    "vfx.line_create_bezier": "Create a Bezier line with start, end, controlPoint1, controlPoint2, and segments.",
    "animation.clip_create": "Create an AnimationClip; pass clipPath and optional frameRate/legacy settings in properties.",
    "animation.controller_create": "Create an AnimatorController; pass controllerPath in properties.",
}

_READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "find_",
    "validate",
    "ping",
    "status",
    "read",
    "lookup",
    "check",
    "inspect",
)
_READ_ACTIONS = {
    "get",
    "search",
    "list",
    "info",
    "get_info",
    "get_active",
    "get_hierarchy",
    "get_build_settings",
    "get_components",
    "screenshot",
    "screenshot_multiview",
    "raycast",
    "raycast_all",
    "linecast",
    "shapecast",
    "overlap",
}
_READ_ACTION_VERBS = {
    "check",
    "compare",
    "find",
    "get",
    "info",
    "inspect",
    "list",
    "lookup",
    "ping",
    "read",
    "search",
    "status",
    "validate",
}
_NON_BATCH_TOOLS = {
    "execute_code",
    "generate_audio",
    "generate_image",
    "generate_model",
    "import_model",
    "import_model_file",
    "refresh_unity",
    "run_tests",
}
_NON_BATCH_ACTION_PARTS = {
    "bake_start",
    "build",
    "add_package",
    "remove_package",
    "embed_package",
    "resolve_packages",
    "memory_take_snapshot",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "tool",
    "unity",
    "manage",
    "with",
}


@dataclass(frozen=True)
class OperationSpec:
    name: str
    tool_name: str
    action: str | None
    category: str
    summary: str
    guidance: str
    required_args: tuple[str, ...]
    optional_args: tuple[str, ...]
    parameters: dict[str, Any]
    aliases: str
    mutating: bool
    batch_safe: bool

    @property
    def parallel_safe(self) -> bool:
        return self.batch_safe and not self.mutating


def _enum_values(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    values = schema.get("enum")
    if isinstance(values, list):
        return [str(value) for value in values if value is not None]
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list):
            found: list[str] = []
            for branch in branches:
                found.extend(_enum_values(branch))
            return list(dict.fromkeys(found))
    return []


def _category(tool_name: str) -> str:
    if tool_name in _TOOL_CATEGORIES:
        return _TOOL_CATEGORIES[tool_name]
    direct = _DIRECT_NAMES.get(tool_name)
    if direct:
        return direct.split(".", 1)[0]
    return tool_name.split("_", 1)[0]


def _summary(description: str | None, *, action: str | None, tool_name: str) -> str:
    text = " ".join((description or "").replace("\ufffd", "-").strip().split())
    if text:
        first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    else:
        first = tool_name.replace("_", " ")
    if action:
        return f"{action.replace('_', ' ')} — {first[:180]}"
    return first[:220]


def _action_guidance(description: str | None, action: str | None) -> str:
    if not description or not action:
        return ""
    clean = description.replace("\ufffd", "-")
    exact = re.compile(rf"^\s*[-*]?\s*{re.escape(action)}\s*:\s*(.+)$", re.IGNORECASE)
    for line in clean.splitlines():
        match = exact.match(line)
        if match:
            return " ".join(match.group(1).split())[:500]
    for line in clean.splitlines():
        normalized = " ".join(line.split())
        if (
            action.casefold() in normalized.casefold()
            and len(normalized) > len(action) + 4
        ):
            return normalized[:500]
    return ""


def _is_read_only(tool_name: str, action: str | None) -> bool:
    if tool_name.startswith(("find_", "get_", "unity_", "validate_")):
        return True
    if tool_name == "read_console":
        return action in {None, "get"}
    if action:
        return (
            action in _READ_ACTIONS
            or action.startswith(_READ_PREFIXES)
            or bool(set(action.casefold().split("_")) & _READ_ACTION_VERBS)
        )
    return False


def _schema_hint(schema: dict[str, Any]) -> dict[str, Any]:
    hint: dict[str, Any] = {}
    schema_type = schema.get("type")
    if schema_type:
        hint["type"] = schema_type
    enums = _enum_values(schema)
    if enums:
        hint["enum"] = enums[:40]
    description = " ".join(str(schema.get("description") or "").split())
    if description:
        hint["description"] = description[:240]
    default = schema.get("default")
    if default is not None:
        hint["default"] = default
    if schema_type == "array" and isinstance(schema.get("items"), dict):
        hint["items"] = _schema_hint(schema["items"])
    return hint or {"type": "any"}


def build_catalog(tools: Sequence[Tool]) -> tuple[OperationSpec, ...]:
    """Expand backend tools into searchable action-level operations."""
    operations: list[OperationSpec] = []
    used_names: set[str] = set()
    for tool in sorted(tools, key=lambda item: item.name):
        if tool.name in _EXCLUDED_TOOLS:
            continue
        schema = tool.inputSchema or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        if not isinstance(properties, dict):
            properties = {}
        actions = (
            _enum_values(properties.get("action"))
            or list(_KNOWN_ACTIONS.get(tool.name, ()))
            or [None]
        )
        required = set(schema.get("required") or [])
        category = _category(tool.name)

        for action in actions:
            if action is None:
                name = _DIRECT_NAMES.get(tool.name, f"{category}.{tool.name}")
            else:
                name = _OPERATION_NAME_OVERRIDES.get(
                    (tool.name, action), f"{category}.{action}"
                )
            if name in used_names:
                name = f"{category}.{tool.name}.{action or 'call'}"
            used_names.add(name)

            arg_names = [
                key for key in properties if key not in {"action", "unity_instance"}
            ]
            allowlist = _OPERATION_PARAMETER_ALLOWLIST.get(name)
            if allowlist is None and action is not None:
                allowlist = _TOOL_ACTION_PARAMETER_ALLOWLIST.get((tool.name, action))
            if allowlist is not None:
                allowed = set(allowlist)
                arg_names = [key for key in arg_names if key in allowed]
            action_required = set(_ACTION_REQUIREMENTS.get(name, ()))
            required_args = tuple(
                key for key in arg_names if key in required or key in action_required
            )
            optional_args = tuple(key for key in arg_names if key not in required)
            optional_args = tuple(
                key for key in optional_args if key not in action_required
            )
            parameters = {key: _schema_hint(properties[key]) for key in arg_names}
            mutating = not _is_read_only(tool.name, action)
            batch_safe = tool.name not in _NON_BATCH_TOOLS and not any(
                part in (action or "") for part in _NON_BATCH_ACTION_PARTS
            )
            aliases = " ".join(
                part
                for part in (
                    tool.name.replace("_", " "),
                    (action or "").replace("_", " "),
                    _ALIASES.get(name, ""),
                )
                if part
            )
            operations.append(
                OperationSpec(
                    name=name,
                    tool_name=tool.name,
                    action=action,
                    category=category,
                    summary=_summary(
                        tool.description, action=action, tool_name=tool.name
                    ),
                    guidance=_GUIDANCE.get(
                        name, _action_guidance(tool.description, action)
                    ),
                    required_args=required_args,
                    optional_args=optional_args,
                    parameters=parameters,
                    aliases=aliases,
                    mutating=mutating,
                    batch_safe=batch_safe,
                )
            )
    return tuple(operations)


_TOKEN_TRANSLATIONS = {
    "объект": "object",
    "объекты": "objects",
    "куб": "cube",
    "сфера": "sphere",
    "сцена": "scene",
    "сцену": "scene",
    "иерархия": "hierarchy",
    "иерархию": "hierarchy",
    "тест": "test",
    "тесты": "tests",
    "редактор": "editor",
    "ассет": "asset",
    "ассеты": "assets",
    "ресурсы": "assets",
    "скрипт": "script",
    "скрипты": "scripts",
    "код": "code",
    "ошибка": "error",
    "ошибки": "errors",
    "предупреждение": "warning",
    "предупреждения": "warnings",
    "консоль": "console",
    "компонент": "component",
    "компоненты": "components",
    "материал": "material",
    "текстура": "texture",
    "шейдер": "shader",
    "физика": "physics",
    "луч": "raycast",
    "коллайдер": "collider",
    "камера": "camera",
    "скриншот": "screenshot",
    "изображение": "image",
    "модель": "model",
    "анимация": "animation",
    "частицы": "particle",
    "эффект": "effect",
    "профайлер": "profiler",
    "сборка": "build",
    "пакет": "package",
    "префаб": "prefab",
    "меш": "mesh",
    "вершины": "vertices",
    "грани": "faces",
    "ребра": "edges",
    "фаска": "bevel",
    "пауза": "pause",
    "игра": "game",
}

_TOKEN_STEMS = (
    ("созда", "create"),
    ("сдела", "create"),
    ("добав", "add"),
    ("удал", "delete"),
    ("най", "find"),
    ("ищ", "search"),
    ("запуст", "run"),
    ("включ", "enable"),
    ("выключ", "disable"),
    ("останов", "stop"),
    ("обнов", "refresh"),
    ("компил", "compile"),
    ("воспроиз", "play"),
    ("перемест", "move"),
    ("повер", "rotate"),
    ("масштаб", "scale"),
    ("переимен", "rename"),
    ("прове", "validate"),
    ("получ", "get"),
    ("покаж", "get"),
    ("сним", "screenshot"),
    ("вершин", "vertices"),
    ("гран", "faces"),
    ("ребр", "edges"),
    ("выдав", "extrude"),
)


def _translate_token(token: str) -> str:
    translated = _TOKEN_TRANSLATIONS.get(token)
    if translated:
        return translated
    if any("а" <= char <= "я" or char == "ё" for char in token):
        for stem, replacement in _TOKEN_STEMS:
            if token.startswith(stem):
                return replacement
    return token


def _token_list(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9а-яё]+", text.casefold().replace("_", " "))
    return [
        translated
        for token in raw
        if (translated := _translate_token(token)) not in _STOPWORDS
    ]


def _tokens(text: str) -> set[str]:
    return set(_token_list(text))


def _char_ngrams(text: str, size: int = 3) -> set[str]:
    compact = re.sub(r"[^a-z0-9]+", "", text.casefold())
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def _fuzzy_similarity(query_tokens: set[str], document_tokens: set[str]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    total = 0.0
    for query_token in query_tokens:
        best = max(
            SequenceMatcher(None, query_token, candidate).ratio()
            for candidate in document_tokens
        )
        if best >= 0.72:
            total += best
    return total / len(query_tokens)


def search_operations(
    query: str,
    *,
    operations: Iterable[OperationSpec],
    limit: int = 6,
    category: str | None = None,
) -> list[tuple[float, OperationSpec]]:
    """Rank operations with multilingual BM25, exact and typo-tolerant signals."""
    normalized = query.strip().casefold()
    query_list = _token_list(normalized)
    query_tokens = set(query_list)
    candidates = [
        item for item in operations if not category or item.category == category
    ]
    if not normalized:
        return [(1.0, item) for item in candidates[: max(1, min(int(limit), 12))]]
    if not query_tokens:
        return []

    documents: list[list[str]] = []
    document_frequency: Counter[str] = Counter()
    for operation in candidates:
        document = _token_list(
            " ".join(
                (
                    operation.name,
                    operation.action or "",
                    operation.aliases,
                    operation.summary,
                    operation.guidance,
                )
            )
        )
        documents.append(document)
        document_frequency.update(set(document))
    average_length = (
        sum(len(document) for document in documents) / len(documents)
        if documents
        else 1.0
    )

    scored: list[tuple[float, OperationSpec]] = []
    for operation, document in zip(candidates, documents, strict=True):
        name = operation.name.casefold()
        name_tokens = _tokens(name)
        action_tokens = _tokens(operation.action or "")
        alias_tokens = _tokens(operation.aliases)
        summary_tokens = _tokens(operation.summary)
        score = 0.0
        translated_query = " ".join(query_list)
        if translated_query == name.replace(".", " ") or normalized == name:
            score += 45
        elif translated_query in name.replace(".", " ") or normalized in name:
            score += 16
        score += 8 * len(query_tokens & name_tokens)
        score += 10 * len(query_tokens & action_tokens)
        score += 5 * len(query_tokens & alias_tokens)
        score += len(query_tokens & summary_tokens)
        if action_tokens and action_tokens <= query_tokens:
            score += 14

        frequencies = Counter(document)
        length_normalizer = 1 - 0.75 + 0.75 * len(document) / max(average_length, 1)
        for token in query_tokens:
            frequency = frequencies[token]
            if not frequency:
                continue
            inverse_frequency = log(
                1
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            score += (
                3.0
                * inverse_frequency
                * (frequency * 2.2 / (frequency + 1.2 * length_normalizer))
            )

        document_tokens = set(document)
        score += 6 * _fuzzy_similarity(query_tokens, document_tokens)
        query_ngrams = _char_ngrams(translated_query)
        name_ngrams = _char_ngrams(name)
        if query_ngrams and name_ngrams:
            score += (
                4 * len(query_ngrams & name_ngrams) / len(query_ngrams | name_ngrams)
            )

        specialized_terms = _SPECIALIZED_CATEGORY_TERMS.get(operation.category)
        if specialized_terms and not query_tokens.intersection(specialized_terms):
            score *= 0.22
        for token in query_tokens:
            if any(
                candidate.startswith(token) or token.startswith(candidate)
                for candidate in name_tokens
            ):
                score += 1
        if score > 0:
            scored.append((score, operation))
    scored.sort(key=lambda item: (-item[0], item[1].mutating, item[1].name))
    return scored[: max(1, min(int(limit), 12))]


def categories(operations: Sequence[OperationSpec]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for operation in operations:
        counts[operation.category] = counts.get(operation.category, 0) + 1
    return [{"name": name, "operation_count": counts[name]} for name in sorted(counts)]


def descriptor(
    score: float,
    operation: OperationSpec,
    *,
    include_schema: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "operation": operation.name,
        "category": operation.category,
        "summary": operation.summary,
        "required_args": list(operation.required_args),
        "mutating": operation.mutating,
        "batch_safe": operation.batch_safe,
        "parallel_safe": operation.parallel_safe,
        "score": round(score, 3),
    }
    if include_schema:
        result["optional_args"] = list(operation.optional_args)
        result["parameters"] = operation.parameters
        if operation.guidance:
            result["guidance"] = operation.guidance
        if operation.name in _EXAMPLES:
            result["example_args"] = _EXAMPLES[operation.name]
    return result
