import json
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client
from mcp.types import TextContent, Tool
from pydantic import RootModel

from unity_mcp_efficient import server
from unity_mcp_efficient.backend import BackendResult
from unity_mcp_efficient.result_store import ResultStore


class FakeBackend:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [
            Tool(
                name="manage_gameobject",
                description="Performs CRUD operations on GameObjects. "
                + "noise " * 500,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {"enum": ["create", "modify"]},
                        "target": {"type": ["string", "integer"]},
                        "name": {"type": "string"},
                    },
                    "required": ["action"],
                },
            )
        ]

    async def call(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        if arguments["action"] == "create":
            data = {
                "success": True,
                "data": {"id": 77, "name": arguments.get("name", "Object")},
            }
        else:
            data = {"success": True, "data": {"target": arguments["target"]}}
        return BackendResult(
            data=data,
            content=[TextContent(type="text", text=json.dumps(data))],
            is_error=False,
        )

    async def read_resource(self, uri):
        return {"uri": uri, "playing": False}


@pytest.fixture
def fake_backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(server, "backend", fake)
    monkeypatch.setattr(server, "_catalog", ())
    monkeypatch.setattr(server, "_catalog_at", 0.0)
    return fake


@pytest.mark.asyncio
async def test_public_surface_is_six_small_tools(fake_backend):
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "search_capabilities",
            "call_operation",
            "get_result",
            "batch_operations",
            "inspect_unity",
            "get_viewport",
        }
        assert sum(len(tool.description or "") for tool in tools) < 600


@pytest.mark.asyncio
async def test_text_only_response_avoids_duplicate_structured_payload(fake_backend):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "call_operation",
            {
                "operation": "gameobject.create",
                "arguments": {"name": "Cube"},
            },
        )
        assert result.is_error is False
        assert result.structured_content is None
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert payload["meta"]["result_id"].startswith("res_")


@pytest.mark.asyncio
async def test_explicit_request_id_suppresses_duplicate_mutation(
    fake_backend, monkeypatch
):
    monkeypatch.setattr(server, "store", ResultStore())
    async with Client(server.mcp) as client:
        arguments = {
            "operation": "gameobject.create",
            "arguments": {"name": "Crate"},
            "request_id": "create-crate-once",
        }
        first = await client.call_tool("call_operation", arguments)
        second = await client.call_tool("call_operation", arguments)
        first_payload = json.loads(first.content[0].text)
        second_payload = json.loads(second.content[0].text)

        assert first_payload["ok"] is True
        assert second_payload["ok"] is True
        assert second_payload["duplicate_suppressed"] is True
        assert second_payload["meta"]["result_id"] == first_payload["meta"]["result_id"]
        assert len(fake_backend.calls) == 1

        mismatch = await client.call_tool(
            "call_operation",
            {
                **arguments,
                "arguments": {"name": "Different"},
            },
        )
        assert "different arguments" in json.loads(mismatch.content[0].text)["error"]
        assert len(fake_backend.calls) == 1


@pytest.mark.asyncio
async def test_sequential_batch_resolves_prior_step_data(fake_backend):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "operations": [
                    {"operation": "gameobject.create", "arguments": {"name": "Cube"}},
                    {
                        "operation": "gameobject.modify",
                        "arguments": {"target": "$steps.0.data.id"},
                    },
                ]
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert fake_backend.calls[1][1]["target"] == 77


@pytest.mark.asyncio
async def test_workflow_select_emit_keeps_intermediate_payload_server_side(
    fake_backend,
):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "response_mode": "emits",
                "operations": [
                    {"operation": "gameobject.create", "arguments": {"name": "Cube"}},
                    {
                        "kind": "select",
                        "from": "$steps.0.data",
                        "fields": ["id"],
                    },
                    {"kind": "emit", "value": "$steps.1.id"},
                ],
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert payload["data"]["emits"] == [77]
        assert "Object" not in result.content[0].text


@pytest.mark.asyncio
async def test_workflow_foreach_expands_locally_and_sequentially(fake_backend):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "operations": [
                    {"kind": "emit", "value": [{"name": "A"}, {"name": "B"}]},
                    {
                        "kind": "foreach",
                        "items": "$steps.0",
                        "operation": "gameobject.create",
                        "arguments": {"name": "$item.name"},
                    },
                ]
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert [arguments["name"] for _, arguments in fake_backend.calls] == ["A", "B"]


@pytest.mark.asyncio
async def test_batch_request_id_suppresses_duplicate_workflow(
    fake_backend, monkeypatch
):
    monkeypatch.setattr(server, "store", ResultStore())
    request = {
        "request_id": "tree-batch-once",
        "operations": [
            {"operation": "gameobject.create", "arguments": {"name": "Tree"}}
        ],
    }
    async with Client(server.mcp) as client:
        first = await client.call_tool("batch_operations", request)
        second = await client.call_tool("batch_operations", request)

    assert json.loads(first.content[0].text)["ok"] is True
    second_payload = json.loads(second.content[0].text)
    assert second_payload["duplicate_suppressed"] is True
    assert second_payload["request_id"] == "tree-batch-once"
    assert len(fake_backend.calls) == 1


@pytest.mark.asyncio
async def test_workflow_assert_stops_later_mutation(fake_backend):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "operations": [
                    {"kind": "emit", "value": 7},
                    {
                        "kind": "assert",
                        "condition": {"left": "$steps.0", "op": "eq", "value": 8},
                        "message": "unexpected count",
                    },
                    {"operation": "gameobject.create", "arguments": {"name": "Never"}},
                ]
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is False
        assert payload["completed"] == 2
        assert fake_backend.calls == []


@pytest.mark.asyncio
async def test_parallel_rejects_mutations_before_execution(fake_backend):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "execution": "parallel",
                "operations": [{"operation": "gameobject.create", "arguments": {}}],
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is False
        assert "read-only" in payload["error"]
        assert fake_backend.calls == []


def test_revision_data_ignores_poll_timestamps_but_keeps_state():
    first = {"sequence": 1, "observed_at_unix_ms": 100, "editor": {"isFocused": True}}
    second = {"sequence": 2, "observed_at_unix_ms": 200, "editor": {"isFocused": True}}
    changed = {
        "sequence": 3,
        "observed_at_unix_ms": 300,
        "editor": {"isFocused": False},
    }
    assert server._stable_revision_data(first) == server._stable_revision_data(second)
    assert server._stable_revision_data(first) != server._stable_revision_data(changed)


class TypedResultBackend:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [
            Tool(
                name="refresh_unity",
                description="Refresh Unity assets and compile scripts.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="run_tests",
                description="Start Unity tests asynchronously.",
                inputSchema={
                    "type": "object",
                    "properties": {"mode": {"type": "string"}},
                },
            ),
            Tool(
                name="manage_editor",
                description="Control Unity editor state.",
                inputSchema={
                    "type": "object",
                    "properties": {"action": {"enum": ["play", "stop"]}},
                    "required": ["action"],
                },
            ),
        ]

    async def call(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        if name == "refresh_unity":
            payload = {"success": True, "message": "Asset refresh started."}
        elif name == "run_tests":
            payload = {
                "success": True,
                "message": "Test job started.",
                "data": {
                    "job_id": "job-239",
                    "status": "running",
                    "mode": "EditMode",
                    "unneeded": ["large detail"] * 20,
                },
            }
        elif arguments["action"] == "play":
            payload = {
                "success": False,
                "data": {"reason": "no_unity_session"},
            }
        else:
            payload = {
                "success": False,
                "data": {"reason": "stale_status"},
            }
        return BackendResult(
            data=RootModel[dict](root=payload),
            content=[],
            is_error=False,
        )

    async def read_resource(self, uri):
        return {"uri": uri}


class PollBackend:
    def __init__(self):
        self.calls = 0

    async def list_tools(self):
        return [
            Tool(
                name="get_test_job",
                description="Get an asynchronous test job.",
                inputSchema={
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            )
        ]

    async def call(self, name, arguments, timeout=None):
        self.calls += 1
        status = "completed" if self.calls >= 2 else "running"
        return BackendResult(
            data={"success": True, "data": {"status": status, "passed": 239}},
            content=[],
            is_error=False,
        )


class SessionBackend:
    def __init__(self):
        self.sessions = 0
        self.calls = 0

    async def list_tools(self):
        return [
            Tool(
                name="find_gameobjects",
                description="Find GameObjects.",
                inputSchema={
                    "type": "object",
                    "properties": {"search_term": {"type": "string"}},
                },
            )
        ]

    async def call(self, name, arguments, timeout=None):
        self.calls += 1
        return BackendResult(
            data={"success": True, "data": []}, content=[], is_error=False
        )

    @asynccontextmanager
    async def session(self):
        self.sessions += 1
        yield self


@pytest.mark.asyncio
async def test_sequential_read_batch_reuses_one_backend_session(monkeypatch):
    fake = SessionBackend()
    monkeypatch.setattr(server, "backend", fake)
    monkeypatch.setattr(server, "_catalog", ())
    monkeypatch.setattr(server, "_catalog_at", 0.0)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "operations": [
                    {
                        "operation": "gameobject.find",
                        "arguments": {"search_term": "Tree"},
                    },
                    {
                        "operation": "gameobject.find",
                        "arguments": {"search_term": "Rock"},
                    },
                ]
            },
        )
    assert json.loads(result.content[0].text)["ok"] is True
    assert fake.sessions == 1
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_workflow_poll_returns_only_final_state(monkeypatch):
    fake = PollBackend()
    monkeypatch.setattr(server, "backend", fake)
    monkeypatch.setattr(server, "_catalog", ())
    monkeypatch.setattr(server, "_catalog_at", 0.0)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "batch_operations",
            {
                "response_mode": "summary",
                "operations": [
                    {
                        "kind": "poll",
                        "operation": "tests.result",
                        "arguments": {"job_id": "job-1"},
                        "until": {
                            "path": "data.status",
                            "op": "eq",
                            "value": "completed",
                        },
                        "interval_ms": 100,
                        "timeout_ms": 2_000,
                    }
                ],
            },
        )
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert fake.calls == 2
        assert payload["data"]["steps"][0]["attempts"] == 2


@pytest.fixture
def typed_backend(monkeypatch):
    fake = TypedResultBackend()
    monkeypatch.setattr(server, "backend", fake)
    monkeypatch.setattr(server, "_catalog", ())
    monkeypatch.setattr(server, "_catalog_at", 0.0)
    return fake


@pytest.mark.asyncio
async def test_typed_refresh_result_is_json_and_recoverable(typed_backend):
    async with Client(server.mcp) as client:
        called = await client.call_tool(
            "call_operation", {"operation": "editor.refresh"}
        )
        payload = json.loads(called.content[0].text)
        assert payload["ok"] is True
        result_id = payload["meta"]["result_id"]

        recovered = await client.call_tool("get_result", {"result_id": result_id})
        raw = json.loads(recovered.content[0].text)
        assert raw["ok"] is True
        assert raw["data"]["data"]["success"] is True


@pytest.mark.asyncio
async def test_typed_test_start_returns_compact_job_contract(typed_backend):
    async with Client(server.mcp) as client:
        called = await client.call_tool(
            "call_operation",
            {"operation": "tests.run", "arguments": {"mode": "EditMode"}},
        )
        payload = json.loads(called.content[0].text)
        assert payload["ok"] is True
        assert payload["data"] == {
            "job_id": "job-239",
            "status": "running",
            "mode": "EditMode",
            "message": "Test job started.",
        }
        assert payload["meta"]["result_id"].startswith("res_")


@pytest.mark.asyncio
async def test_domain_reload_failure_controls_outer_status(typed_backend):
    async with Client(server.mcp) as client:
        play = await client.call_tool("call_operation", {"operation": "editor.play"})
        play_payload = json.loads(play.content[0].text)
        assert play_payload["ok"] is False
        assert play_payload["reason"] == "no_unity_session"
        assert play_payload["retryable"] is True
        assert play_payload["retry_safe"] is False
        assert play_payload["state_may_have_changed"] is True

        stop = await client.call_tool("call_operation", {"operation": "editor.stop"})
        stop_payload = json.loads(stop.content[0].text)
        assert stop_payload["ok"] is False
        assert stop_payload["reason"] == "stale_status"
        assert stop_payload["retry_after_ms"] == 1000


@pytest.mark.asyncio
async def test_postprocess_failure_keeps_result_handle(typed_backend, monkeypatch):
    def broken_preview(operation, value):
        raise TypeError("preview failed")

    monkeypatch.setattr(server, "prepare_preview", broken_preview)
    async with Client(server.mcp) as client:
        called = await client.call_tool(
            "call_operation", {"operation": "editor.refresh"}
        )
        payload = json.loads(called.content[0].text)
        assert payload["ok"] is True
        assert payload["meta"]["postprocess_error"] == "preview failed"
        result_id = payload["meta"]["result_id"]

        recovered = await client.call_tool("get_result", {"result_id": result_id})
        assert json.loads(recovered.content[0].text)["ok"] is True


@pytest.mark.asyncio
async def test_inspection_does_not_mask_missing_unity_session(
    typed_backend, monkeypatch
):
    async def unavailable(uri, timeout=None):
        return {"success": False, "data": {"reason": "no_unity_session"}}

    monkeypatch.setattr(typed_backend, "read_resource", unavailable)
    async with Client(server.mcp) as client:
        inspected = await client.call_tool(
            "inspect_unity", {"scope": "state", "detail": "low"}
        )
        payload = json.loads(inspected.content[0].text)
        assert payload["ok"] is False
        assert payload["reason"] == "no_unity_session"
        assert payload["retryable"] is True
        assert payload["retry_safe"] is True


@pytest.mark.asyncio
async def test_inspection_recognizes_prose_missing_session_reason(
    typed_backend, monkeypatch
):
    async def unavailable(uri, timeout=None):
        return {
            "success": False,
            "data": {"reason": "Unity session not available; please retry"},
        }

    monkeypatch.setattr(typed_backend, "read_resource", unavailable)
    async with Client(server.mcp) as client:
        inspected = await client.call_tool(
            "inspect_unity", {"scope": "state", "detail": "low"}
        )
        payload = json.loads(inspected.content[0].text)
        assert payload["ok"] is False
        assert payload["retryable"] is True
        assert payload["retry_after_ms"] == 1000
        assert payload["retry_safe"] is True
