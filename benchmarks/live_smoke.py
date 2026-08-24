"""Read-only live smoke test for the facade and an open Unity Editor."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import Client

from unity_mcp_efficient import server


def _payload(result: Any) -> dict[str, Any]:
    return json.loads(result.content[0].text)


async def _inspect_state(client: Client) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for _ in range(3):
        state = _payload(
            await client.call_tool(
                "inspect_unity", {"scope": "state", "detail": "low"}
            )
        )
        if state.get("ok") or not state.get("retryable"):
            return state
        await asyncio.sleep(max(int(state.get("retry_after_ms", 1000)), 100) / 1000)
    return state


async def smoke() -> dict[str, Any]:
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        search = _payload(
            await client.call_tool(
                "search_capabilities",
                {
                    "query": "обновить ассеты и скомпилировать скрипты",
                    "limit": 3,
                    "include_schema": True,
                },
            )
        )
        state = await _inspect_state(client)
        scene = _payload(
            await client.call_tool(
                "batch_operations",
                {
                    "execution": "sequential",
                    "response_mode": "summary",
                    "operations": [
                        {"operation": "scene.get_active"},
                        {
                            "operation": "scene.get_hierarchy",
                            "arguments": {"max_depth": 2, "max_nodes": 30},
                        },
                    ],
                },
            )
        )
    return {
        "tool_count": len(tools),
        "tool_names": sorted(tool.name for tool in tools),
        "search_top": [match["operation"] for match in search.get("matches", [])],
        "state_ok": state.get("ok"),
        "state_reason": state.get("reason"),
        "scene_ok": scene.get("ok"),
        "scene_completed": scene.get("completed"),
        "scene_result_id": (scene.get("meta") or {}).get("result_id"),
    }


def main() -> None:
    result = asyncio.run(smoke())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["tool_count"] != 6:
        raise SystemExit(1)
    if not result["search_top"] or result["search_top"][0] != "editor.refresh":
        raise SystemExit(1)
    if not result["state_ok"] or not result["scene_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
