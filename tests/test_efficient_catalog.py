from mcp.types import Tool

from unity_mcp_efficient.catalog import build_catalog, descriptor, search_operations


def _tool(name: str, action_schema: dict) -> Tool:
    return Tool(
        name=name,
        description="A deliberately long backend description that is indexed, not exposed.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": action_schema,
                "target": {"type": "string", "description": "Object target"},
            },
            "required": ["action"],
        },
    )


def test_expands_enum_actions_and_excludes_action_argument():
    catalog = build_catalog([_tool("manage_scene", {"enum": ["get_active", "save"]})])
    assert [item.name for item in catalog] == ["scene.get_active", "scene.save"]
    assert catalog[0].required_args == ()
    assert catalog[0].mutating is False
    assert catalog[1].mutating is True


def test_known_open_actions_are_searchable_without_full_description():
    catalog = build_catalog([_tool("manage_probuilder", {"type": "string"})])
    results = search_operations("create a cube primitive", operations=catalog)
    assert results[0][1].name == "probuilder.create_shape"
    assert any(item.name == "probuilder.get_mesh_info" for item in catalog)


def test_editor_intents_outrank_unrequested_specialized_categories():
    catalog = build_catalog(
        [
            _tool("manage_animation", {"type": "string"}),
            _tool("manage_vfx", {"type": "string"}),
            _tool("manage_editor", {"enum": ["play", "stop"]}),
            Tool(
                name="refresh_unity",
                description="Refresh the AssetDatabase and compile scripts.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
    )
    refresh = search_operations(
        "refresh asset database and compile scripts", operations=catalog, limit=5
    )
    assert refresh[0][1].name == "editor.refresh"

    play = search_operations(
        "enter play mode stop play mode", operations=catalog, limit=5
    )
    assert {item.name for _, item in play[:2]} == {"editor.play", "editor.stop"}
    assert all(item.category != "animation" for _, item in play[:2])


def test_action_specific_schema_hides_unrelated_manager_arguments():
    tool = Tool(
        name="manage_asset",
        description="Import, create, modify, delete, or search Unity assets.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"enum": ["search"]},
                "path": {"type": "string"},
                "properties": {"type": "object"},
                "destination": {"type": "string"},
                "search_pattern": {"type": "string"},
                "page_size": {"type": "integer"},
            },
            "required": ["action", "path"],
        },
    )
    operation = build_catalog([tool])[0]
    details = descriptor(10, operation, include_schema=True)
    assert details["required_args"] == ["path"]
    assert details["optional_args"] == ["search_pattern", "page_size"]
    assert "properties" not in details["parameters"]
    assert "destination" not in details["parameters"]


def test_asset_database_search_does_not_collide_with_generated_model_search():
    catalog = build_catalog(
        [
            Tool(
                name="import_model",
                description="Search and import generated models.",
                inputSchema={
                    "type": "object",
                    "properties": {"action": {"enum": ["search", "import"]}},
                    "required": ["action"],
                },
            ),
            _tool("manage_asset", {"enum": ["search"]}),
        ]
    )
    names = {item.name: item.tool_name for item in catalog}
    assert names["asset.search"] == "manage_asset"
    assert names["asset.generated_model_search"] == "import_model"


def test_multilingual_search_routes_common_russian_unity_intents():
    catalog = build_catalog(
        [
            _tool("manage_gameobject", {"enum": ["create", "delete"]}),
            _tool("manage_editor", {"enum": ["play", "stop"]}),
            Tool(
                name="refresh_unity",
                description="Refresh the AssetDatabase and compile scripts.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="run_tests",
                description="Run Unity tests.",
                inputSchema={
                    "type": "object",
                    "properties": {"mode": {"type": "string"}},
                },
            ),
        ]
    )

    assert search_operations("создать куб", operations=catalog)[0][1].name == (
        "gameobject.create"
    )
    assert search_operations("запустить тесты", operations=catalog)[0][1].name == (
        "tests.run"
    )
    assert (
        search_operations(
            "обновить ассеты и скомпилировать скрипты", operations=catalog
        )[0][1].name
        == "editor.refresh"
    )


def test_typo_tolerant_search_and_unknown_query_do_not_return_noise():
    catalog = build_catalog(
        [
            _tool("manage_gameobject", {"enum": ["create", "delete"]}),
            _tool("manage_scene", {"enum": ["get_hierarchy", "save"]}),
        ]
    )
    assert search_operations("crate gameobjet", operations=catalog)[0][1].name == (
        "gameobject.create"
    )
    assert search_operations("щъыьнеп неизвестно", operations=catalog) == []


def test_physics_action_contract_removes_unrelated_union_parameters():
    tool = Tool(
        name="manage_physics",
        description="Physics queries and mutations.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"enum": ["raycast"]},
                "origin": {"type": "array"},
                "direction": {"type": "array"},
                "max_distance": {"type": "number"},
                "layer_mask": {"type": "integer"},
                "query_trigger_interaction": {"type": "string"},
                "force": {"type": "array"},
                "joint_type": {"type": "string"},
                "settings": {"type": "object"},
            },
            "required": ["action"],
        },
    )
    operation = build_catalog([tool])[0]
    details = descriptor(10, operation, include_schema=True)

    assert details["required_args"] == ["origin", "direction"]
    assert details["optional_args"] == [
        "max_distance",
        "layer_mask",
        "query_trigger_interaction",
    ]
    assert "force" not in details["parameters"]
    assert details["example_args"]["direction"] == [0, -1, 0]


def test_compound_read_action_is_parallel_safe():
    catalog = build_catalog([_tool("manage_graphics", {"type": "string"})])
    by_name = {operation.name: operation for operation in catalog}

    assert by_name["graphics.stats_get"].parallel_safe is True
    assert by_name["graphics.volume_get_info"].parallel_safe is True
    assert by_name["graphics.pipeline_set_quality"].parallel_safe is False
