from unity_mcp_efficient.compact import compact_result
from unity_mcp_efficient.postprocess import prepare_preview


def test_large_numeric_array_becomes_summary_with_recovery_handle():
    result = compact_result(
        {"vertices": list(range(1_000))},
        mode="compact",
        max_chars=1_000,
        result_id="res_example",
    )
    assert result["data"]["vertices"]["count"] == 1_000
    assert result["meta"]["truncated"] is True
    assert result["meta"]["recovery"]["result_id"] == "res_example"


def test_console_preview_deduplicates_and_drops_stacktraces():
    raw = {
        "entries": [
            {
                "type": "Error",
                "message": "Boom",
                "stackTrace": "very long",
                "file": "A.cs",
                "line": 7,
            },
            {
                "type": "Error",
                "message": "Boom",
                "stackTrace": "very long",
                "file": "A.cs",
                "line": 7,
            },
        ]
    }
    result = prepare_preview("console.get", raw)
    assert result["entry_count"] == 2
    assert result["unique_count"] == 1
    assert result["entries"][0]["repeats"] == 2
    assert len(result["entries"][0]["fingerprint"]) == 10
    assert "stack" not in str(result).casefold()


def test_console_preview_keeps_first_project_frame_without_full_trace():
    raw = {
        "entries": [
            {
                "type": "Error",
                "message": "NullReferenceException: Missing target",
                "stackTrace": (
                    "UnityEngine.Internal.Call()\n"
                    "TreeController.Update() (at Assets/Scripts/TreeController.cs:42)\n"
                    "UnityEngine.PlayerLoop()"
                ),
            }
        ]
    }
    result = prepare_preview("console.get", raw)
    entry = result["entries"][0]
    assert entry["project_frame"].endswith("TreeController.cs:42")
    assert entry["root_cause"] == "NullReferenceException: Missing target"
    assert "PlayerLoop" not in str(result)


def test_probuilder_preview_summarizes_topology_and_preserves_bounds():
    raw = {
        "success": True,
        "data": {
            "name": "TreeMesh",
            "vertices": [[-1, 0, 0], [1, 4, 2], [0, 2, -2]],
            "faces": [[0, 1, 2]] * 100,
        },
    }
    result = prepare_preview("probuilder.get_mesh_info", raw)
    assert result["vertices"]["count"] == 3
    assert result["vertices"]["bounds"] == {
        "min": [-1.0, 0.0, -2.0],
        "max": [1.0, 4.0, 2.0],
    }
    assert result["faces"]["count"] == 100
    assert len(result["faces"]["sample"]) == 3


def test_hierarchy_removes_defaults_but_keeps_shape():
    raw = [
        {
            "name": "Root",
            "instanceID": 42,
            "tag": "Untagged",
            "layer": 0,
            "active": True,
            "components": [{"type": "Transform"}],
            "children": [{"name": "Child", "instanceID": 43, "children": []}],
        }
    ]
    result = prepare_preview("scene.get_hierarchy", raw)
    assert result == [
        {
            "name": "Root",
            "id": 42,
            "components": ["Transform"],
            "children": [{"name": "Child", "id": 43}],
        }
    ]
