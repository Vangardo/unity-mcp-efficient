"""Measure model-visible MCP surface and synthetic hierarchy response size."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from fastmcp import Client

from unity_mcp_efficient.backend import UnityBackend
from unity_mcp_efficient.compact import compact_result
from unity_mcp_efficient.postprocess import prepare_preview
from unity_mcp_efficient.server import mcp


def _serialized_tools(tools: list[Any]) -> str:
    visible = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema,
        }
        for tool in tools
    ]
    return json.dumps(visible, ensure_ascii=False, separators=(",", ":"), default=str)


def _metric(chars: int) -> dict[str, int]:
    return {"chars": chars, "approx_tokens_at_4_chars": math.ceil(chars / 4)}


async def main() -> None:
    async with Client(UnityBackend().url) as upstream:
        old_tools = list(await upstream.list_tools())
    async with Client(mcp) as efficient:
        new_tools = list(await efficient.list_tools())

    old_surface = len(_serialized_tools(old_tools))
    new_surface = len(_serialized_tools(new_tools))

    hierarchy = {
        "success": True,
        "data": [
            {
                "name": f"Object_{index}",
                "instanceID": index,
                "tag": "Untagged",
                "layer": 0,
                "active": True,
                "components": [{"type": "Transform"}, {"type": "MeshRenderer"}],
                "vertices": list(range(300)),
                "children": [],
            }
            for index in range(250)
        ],
    }
    raw = json.dumps(hierarchy, ensure_ascii=False, separators=(",", ":"))
    # Current FastMCP results commonly expose equivalent text and structured payloads.
    legacy_response_chars = len(raw) * 2
    efficient_payload = compact_result(
        prepare_preview("scene.get_hierarchy", hierarchy),
        mode="compact",
        max_chars=8_000,
        result_id="res_benchmark",
    )
    efficient_response_chars = len(
        json.dumps(efficient_payload, ensure_ascii=False, separators=(",", ":"))
    )

    report = {
        "tool_surface": {
            "upstream_tool_count": len(old_tools),
            "efficient_tool_count": len(new_tools),
            "upstream": _metric(old_surface),
            "efficient": _metric(new_surface),
            "reduction_percent": round((1 - new_surface / old_surface) * 100, 2),
        },
        "synthetic_hierarchy_response": {
            "objects": 250,
            "vertices_per_object": 300,
            "legacy_text_plus_structured": _metric(legacy_response_chars),
            "efficient_preview": _metric(efficient_response_chars),
            "reduction_percent": round(
                (1 - efficient_response_chars / legacy_response_chars) * 100, 2
            ),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
