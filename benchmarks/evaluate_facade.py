"""Deterministic quality/token evaluation for the efficient Unity facade."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from unity_mcp_efficient.backend import UnityBackend
from unity_mcp_efficient.catalog import build_catalog, descriptor, search_operations

SEARCH_CASES = (
    ("create a cube", "gameobject.create"),
    ("создать куб", "gameobject.create"),
    ("run edit mode tests", "tests.run"),
    ("запустить тесты", "tests.run"),
    ("refresh assets and compile scripts", "editor.refresh"),
    ("обновить ассеты и скомпилировать скрипты", "editor.refresh"),
    ("enter play mode", "editor.play"),
    ("stop play mode", "editor.stop"),
    ("show console errors", "console.get"),
    ("capture scene viewport", "camera.screenshot"),
    ("inspect scene hierarchy", "scene.get_hierarchy"),
    ("bevel selected mesh edges", "probuilder.bevel_edges"),
    ("raycast against the ground", "physics.raycast"),
    ("create a particle fire effect", "vfx.particle_create"),
    ("build the Unity player", "build.build"),
)


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


async def evaluate() -> dict[str, Any]:
    tools = await UnityBackend().list_tools()
    operations = build_catalog(tools)
    tool_by_name = {tool.name: tool for tool in tools}

    cases: list[dict[str, Any]] = []
    top1 = 0
    top3 = 0
    for query, expected in SEARCH_CASES:
        names = [
            operation.name
            for _, operation in search_operations(query, operations=operations, limit=3)
        ]
        top1 += bool(names and names[0] == expected)
        top3 += expected in names
        cases.append(
            {
                "query": query,
                "expected": expected,
                "top": names,
                "pass": bool(names and names[0] == expected),
            }
        )

    action_argument_total = sum(
        len(operation.required_args) + len(operation.optional_args)
        for operation in operations
    )
    union_argument_total = 0
    for operation in operations:
        schema = tool_by_name[operation.tool_name].inputSchema or {}
        properties = schema.get("properties") or {}
        union_argument_total += len(
            [name for name in properties if name not in {"action", "unity_instance"}]
        )

    schema_chars = sum(
        _json_chars(descriptor(1, operation, include_schema=True))
        for operation in operations
    )
    return {
        "catalog": {
            "tools": len(tools),
            "operations": len(operations),
            "average_optional_args": round(
                sum(len(operation.optional_args) for operation in operations)
                / len(operations),
                2,
            ),
            "max_optional_args": max(
                len(operation.optional_args) for operation in operations
            ),
            "union_argument_total": union_argument_total,
            "action_argument_total": action_argument_total,
            "argument_reduction_percent": round(
                100 * (1 - action_argument_total / union_argument_total), 2
            ),
            "all_action_descriptors_chars": schema_chars,
        },
        "search": {
            "cases": len(SEARCH_CASES),
            "recall_at_1": round(top1 / len(SEARCH_CASES), 3),
            "recall_at_3": round(top3 / len(SEARCH_CASES), 3),
            "failures": [case for case in cases if not case["pass"]],
            "results": cases,
        },
    }


def main() -> None:
    result = asyncio.run(evaluate())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["search"]["recall_at_1"] < 0.9:
        raise SystemExit(1)
    if result["catalog"]["max_optional_args"] > 20:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
