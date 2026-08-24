"""Small client boundary around the upstream MCP for Unity server."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from mcp.types import (
    BlobResourceContents,
    ContentBlock,
    TextContent,
    TextResourceContents,
    Tool,
)

from .serialization import to_jsonable

DEFAULT_BACKEND_URL = "http://127.0.0.1:8080/mcp"


@dataclass(frozen=True)
class BackendResult:
    data: Any
    content: list[ContentBlock]
    is_error: bool


class UnityBackend:
    """Reconnect by default, with explicit short-lived batch sessions."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("UNITY_MCP_BACKEND_URL", DEFAULT_BACKEND_URL)

    async def list_tools(self) -> list[Tool]:
        async with Client(self.url) as client:
            return list(await client.list_tools())

    async def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> BackendResult:
        async with Client(self.url) as client:
            return await _call_client(client, name, arguments, timeout=timeout)

    async def read_resource(self, uri: str, *, timeout: float | None = None) -> Any:
        async with Client(self.url) as client:
            return await _read_client(client, uri, timeout=timeout)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[UnityBackendSession]:
        """Reuse one transport only inside a bounded sequential workflow.

        The next top-level request still reconnects, preserving recovery after a
        Unity domain reload while avoiding handshake cost between ordinary batch
        steps.
        """
        async with Client(self.url) as client:
            yield UnityBackendSession(client)


class UnityBackendSession:
    """Connected backend view used by one bounded facade workflow."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> BackendResult:
        return await _call_client(self._client, name, arguments, timeout=timeout)

    async def read_resource(self, uri: str, *, timeout: float | None = None) -> Any:
        return await _read_client(self._client, uri, timeout=timeout)


async def _call_client(
    client: Client,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    timeout: float | None,
) -> BackendResult:
    result = await client.call_tool(
        name,
        arguments or {},
        timeout=timeout or float(os.getenv("UNITY_MCP_OPERATION_TIMEOUT", "60")),
        raise_on_error=False,
    )
    data = result.data
    if data is None and result.structured_content is not None:
        data = result.structured_content
    if data is None:
        data = _content_data(result.content)
    return BackendResult(
        data=to_jsonable(data),
        content=list(result.content),
        is_error=bool(result.is_error),
    )


async def _read_client(
    client: Client,
    uri: str,
    *,
    timeout: float | None,
) -> Any:
    contents = await asyncio.wait_for(
        client.read_resource(uri),
        timeout=timeout or float(os.getenv("UNITY_MCP_OPERATION_TIMEOUT", "60")),
    )
    decoded = [to_jsonable(_resource_data(item)) for item in contents]
    return decoded[0] if len(decoded) == 1 else decoded


def _decode_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return text


def _content_data(content: list[ContentBlock]) -> Any:
    text_parts = [
        _decode_text(item.text) for item in content if isinstance(item, TextContent)
    ]
    if len(text_parts) == 1:
        return text_parts[0]
    if text_parts:
        return text_parts
    return {"content_types": [item.type for item in content]}


def _resource_data(item: TextResourceContents | BlobResourceContents) -> Any:
    if isinstance(item, TextResourceContents):
        return _decode_text(item.text)
    return {
        "mime_type": item.mimeType,
        "blob_chars": len(item.blob),
        "note": "Binary resource omitted from model context.",
    }
