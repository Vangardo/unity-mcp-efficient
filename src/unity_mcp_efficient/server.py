"""Token-efficient MCP facade for the upstream MCP for Unity server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent, ToolAnnotations

from .backend import BackendResult, UnityBackend
from .catalog import (
    OperationSpec,
    build_catalog,
    categories,
    descriptor,
    search_operations,
)
from .compact import compact_result, looks_like_error
from .postprocess import prepare_arguments, prepare_preview
from .result_store import (
    ResultStore,
    StoredResultInfo,
    default_result_database,
    select_result,
)
from .serialization import to_jsonable
from .workflow import (
    contains_step_reference,
    evaluate_condition,
    resolve_references,
    select_value,
)

mcp = FastMCP(
    "Unity MCP Efficient",
    instructions="Search operations, batch independent work, inspect compactly, expand stored results only when needed.",
)
backend = UnityBackend()
store = ResultStore(database_path=default_result_database())
_catalog: tuple[OperationSpec, ...] = ()
_catalog_at = 0.0
_catalog_lock = asyncio.Lock()


def _text(value: Any) -> ToolResult:
    normalized = to_jsonable(value)
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structured_content=None,
    )


async def _operations(*, refresh: bool = False) -> tuple[OperationSpec, ...]:
    global _catalog, _catalog_at
    if _catalog and not refresh and time.monotonic() - _catalog_at < 60:
        return _catalog
    async with _catalog_lock:
        if _catalog and not refresh and time.monotonic() - _catalog_at < 60:
            return _catalog
        _catalog = build_catalog(await backend.list_tools())
        _catalog_at = time.monotonic()
        return _catalog


async def _resolve(name: str) -> OperationSpec:
    operations = await _operations()
    normalized = name.strip().casefold()
    for operation in operations:
        if operation.name.casefold() == normalized:
            return operation
    suggestions = [
        item.name for _, item in search_operations(name, operations=operations, limit=5)
    ]
    suffix = f" Suggestions: {', '.join(suggestions)}" if suggestions else ""
    raise ValueError(f"Unknown operation: {name}.{suffix}")


def _request_fingerprint(
    spec: OperationSpec,
    arguments: dict[str, Any] | None,
    *,
    unity_instance: str | None,
) -> str:
    prepared = prepare_arguments(spec, arguments, unity_instance=unity_instance)
    canonical = json.dumps(
        {"operation": spec.name, "arguments": prepared},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _data_is_ok(value: Any) -> bool:
    if looks_like_error(value):
        return False
    return not (isinstance(value, dict) and value.get("success") is False)


def _is_ok(result: BackendResult) -> bool:
    return not result.is_error and _data_is_ok(result.data)


_TRANSIENT_REASONS = {
    "no_unity_session",
    "stale_connection",
    "stale_status",
    "unity_reloading",
}

_TRANSIENT_REASON_MARKERS = (
    "unity session not available",
    "no unity session",
    "stale connection",
    "stale status",
    "unity reloading",
)


def _is_transient_reason(reason: str) -> bool:
    normalized = reason.strip().casefold()
    return normalized in _TRANSIENT_REASONS or any(
        marker in normalized for marker in _TRANSIENT_REASON_MARKERS
    )


def _failure_reason(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("reason", "error"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    blocking = value.get("blocking_reasons")
    if isinstance(blocking, list):
        for candidate in blocking:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    nested = value.get("data")
    if isinstance(nested, dict):
        reason = _failure_reason(nested)
        if reason:
            return reason
    for nested in value.values():
        if isinstance(nested, dict):
            reason = _failure_reason(nested)
            if reason:
                return reason
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    reason = _failure_reason(item)
                    if reason:
                        return reason
    status = value.get("status")
    if isinstance(status, str) and status.casefold() in {"error", "failed"}:
        return status
    return None


def _fallback_preview(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return {"type": type(raw).__name__, "preview": str(raw)[:360]}
    selected: dict[str, Any] = {}
    for key in ("success", "status", "job_id", "jobId", "reason", "message", "error"):
        if key in raw:
            selected[key] = raw[key]
    data = raw.get("data")
    if isinstance(data, dict):
        for key in ("status", "job_id", "jobId", "reason", "message", "error"):
            if key in data and key not in selected:
                selected[key] = data[key]
    return selected or {"type": "object", "keys": list(raw)[:16]}


def _format_execution(
    spec: OperationSpec,
    raw: Any,
    *,
    backend_error: bool,
    output_mode: str,
    max_chars: int,
    persist: bool = True,
    stored_info: StoredResultInfo | None = None,
) -> dict[str, Any]:
    if spec.mutating and not persist and stored_info is None:
        raise ValueError("Mutating operation results must be persisted")
    normalized_result = BackendResult(
        data=raw,
        content=[],
        is_error=backend_error,
    )
    ok = _is_ok(normalized_result)
    info = stored_info or (
        store.put(raw, operation=spec.name, mutating=spec.mutating, ok=ok)
        if persist
        else None
    )
    result_id = info.result_id if info else None
    try:
        preview = prepare_preview(spec.name, raw)
        compacted = compact_result(
            preview,
            mode=output_mode,
            max_chars=max_chars,
            result_id=result_id,
            mutating=spec.mutating,
        )
    except Exception as exc:
        compacted = {
            "data": _fallback_preview(raw),
            "meta": {
                "mutating": spec.mutating,
                "postprocess_error": str(exc),
            },
        }
        if result_id:
            compacted["meta"].update(
                result_id=result_id,
                recovery={
                    "result_id": result_id,
                    "action": "Use get_result; do not repeat the operation.",
                },
            )
    compacted["operation"] = spec.name
    compacted["ok"] = ok
    if not ok:
        reason = _failure_reason(raw)
        if reason:
            compacted["reason"] = reason
            if _is_transient_reason(reason):
                compacted["retryable"] = True
                compacted["retry_after_ms"] = 1_000
                compacted["retry_safe"] = not spec.mutating
        if spec.mutating:
            compacted["state_may_have_changed"] = True
    return compacted


async def _execute(
    spec: OperationSpec,
    arguments: dict[str, Any] | None,
    *,
    unity_instance: str | None,
    output_mode: str,
    max_chars: int,
    caller: Any | None = None,
    persist: bool = True,
) -> tuple[dict[str, Any], Any]:
    prepared = prepare_arguments(spec, arguments, unity_instance=unity_instance)
    result = await (caller or backend).call(spec.tool_name, prepared)
    raw = to_jsonable(result.data)
    compacted = _format_execution(
        spec,
        raw,
        backend_error=result.is_error,
        output_mode=output_mode,
        max_chars=max_chars,
        persist=persist,
    )
    return compacted, raw


@asynccontextmanager
async def _batch_caller(*, reuse: bool) -> AsyncIterator[Any]:
    """Use a short backend session when supported; test doubles stay compatible."""
    session_factory = getattr(backend, "session", None)
    if not reuse or session_factory is None:
        yield backend
        return
    async with session_factory() as caller:
        yield caller


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def search_capabilities(
    query: str = "",
    category: str | None = None,
    limit: int = 6,
    include_schema: bool = False,
    refresh: bool = False,
) -> ToolResult:
    """Find operation names and only the argument hints needed next."""
    try:
        operations = await _operations(refresh=refresh)
        if not query.strip():
            return _text(
                {
                    "categories": categories(operations),
                    "hint": "Search with a task phrase.",
                }
            )
        matches = search_operations(
            query, operations=operations, limit=limit, category=category
        )
        return _text(
            {
                "query": query,
                "matches": [
                    descriptor(score, item, include_schema=include_schema)
                    for score, item in matches
                ],
            }
        )
    except Exception as exc:
        return _text({"ok": False, "error": str(exc)})


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def call_operation(
    operation: str,
    arguments: dict[str, Any] | None = None,
    unity_instance: str | None = None,
    output_mode: Literal["compact", "standard", "full"] = "compact",
    max_chars: int = 8_000,
    request_id: str | None = None,
) -> ToolResult:
    """Execute once; request_id safely deduplicates retries of mutations."""
    spec: OperationSpec | None = None
    try:
        spec = await _resolve(operation)
        fingerprint = _request_fingerprint(
            spec, arguments, unity_instance=unity_instance
        )
        if request_id:
            prior = store.get_request(request_id, fingerprint=fingerprint)
            if prior is not None:
                raw, info = prior
                recovered = _format_execution(
                    spec,
                    raw,
                    backend_error=not info.ok,
                    output_mode=output_mode,
                    max_chars=max_chars,
                    persist=False,
                    stored_info=info,
                )
                recovered["duplicate_suppressed"] = True
                recovered["request_id"] = request_id
                return _text(recovered)
        result, _ = await _execute(
            spec,
            arguments,
            unity_instance=unity_instance,
            output_mode=output_mode,
            max_chars=max_chars,
        )
        if request_id:
            result_id = result.get("meta", {}).get("result_id")
            if result_id:
                store.remember_request(
                    request_id,
                    fingerprint=fingerprint,
                    result_id=str(result_id),
                )
                result["request_id"] = request_id
        return _text(result)
    except Exception as exc:
        failure: dict[str, Any] = {
            "ok": False,
            "operation": operation,
            "error": str(exc),
        }
        if spec is not None and spec.mutating:
            failure.update(state_may_have_changed=True, retry_safe=False)
        return _text(failure)


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_result(
    result_id: str,
    path: str = "",
    offset: int = 0,
    limit: int = 50,
    pattern: str | None = None,
    output_mode: Literal["compact", "standard", "full"] = "standard",
    max_chars: int = 12_000,
) -> ToolResult:
    """Page, select, or search a prior result without repeating Unity work."""
    try:
        raw, info = store.get(result_id)
        selected = select_result(
            raw, path=path, offset=offset, limit=limit, pattern=pattern
        )
        result = compact_result(
            selected, mode=output_mode, max_chars=max_chars, result_id=result_id
        )
        result["operation"] = info.operation
        result["ok"] = info.ok
        return _text(result)
    except Exception as exc:
        return _text({"ok": False, "result_id": result_id, "error": str(exc)})


_WORKFLOW_KINDS = {"call", "select", "assert", "poll", "foreach", "emit"}


def _step_kind(step: dict[str, Any]) -> str:
    kind = str(step.get("kind") or "call").casefold()
    if kind not in _WORKFLOW_KINDS:
        raise ValueError(f"Unsupported workflow step kind: {kind}")
    return kind


def _receipt(index: int, kind: str, result: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "step": index,
        "kind": kind,
        "ok": bool(result.get("ok", True)),
    }
    for key in ("operation", "skipped", "attempts", "elapsed_ms", "error"):
        if key in result:
            receipt[key] = result[key]
    meta = result.get("meta")
    if isinstance(meta, dict) and meta.get("result_id"):
        receipt["result_id"] = meta["result_id"]
    data = result.get("data")
    if isinstance(data, dict):
        signal: dict[str, Any] = {}
        for key in (
            "status",
            "success",
            "job_id",
            "jobId",
            "id",
            "name",
            "count",
            "message",
        ):
            if key in data:
                signal[key] = data[key]
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("status", "job_id", "jobId", "id", "name", "count"):
                if key in nested and key not in signal:
                    signal[key] = nested[key]
        if signal:
            receipt["data"] = signal
    return receipt


async def _poll_step(
    step: dict[str, Any],
    spec: OperationSpec,
    previous: list[Any],
    *,
    unity_instance: str | None,
    output_mode: str,
    max_chars: int,
    caller: Any,
) -> tuple[dict[str, Any], Any]:
    if spec.mutating:
        raise ValueError(f"poll requires a read-only operation: {spec.name}")
    until = step.get("until")
    if not isinstance(until, dict):
        raise TypeError("poll step requires an until condition")
    interval_ms = max(100, min(int(step.get("interval_ms") or 500), 10_000))
    timeout_ms = max(100, min(int(step.get("timeout_ms") or 20_000), 55_000))
    arguments = resolve_references(dict(step.get("arguments") or {}), previous)
    started = time.monotonic()
    attempts = 0
    final_result: dict[str, Any] | None = None
    final_raw: Any = None
    while True:
        attempts += 1
        final_result, final_raw = await _execute(
            spec,
            arguments,
            unity_instance=unity_instance,
            output_mode=output_mode,
            max_chars=max_chars,
            caller=caller,
            persist=False,
        )
        if evaluate_condition(until, previous, current=final_raw):
            break
        elapsed_ms = int((time.monotonic() - started) * 1_000)
        if elapsed_ms >= timeout_ms:
            final_result.update(
                ok=False,
                error=f"poll timed out after {elapsed_ms} ms",
                retry_safe=True,
            )
            break
        await asyncio.sleep(min(interval_ms, timeout_ms - elapsed_ms) / 1_000)

    assert final_result is not None
    info = store.put(
        final_raw, operation=spec.name, mutating=False, ok=final_result["ok"]
    )
    final_meta = final_result.setdefault("meta", {})
    final_meta["result_id"] = info.result_id
    if isinstance(final_meta.get("recovery"), dict):
        final_meta["recovery"]["result_id"] = info.result_id
    final_result["attempts"] = attempts
    final_result["elapsed_ms"] = int((time.monotonic() - started) * 1_000)
    return final_result, final_raw


async def _foreach_step(
    step: dict[str, Any],
    spec: OperationSpec,
    previous: list[Any],
    *,
    unity_instance: str | None,
    output_mode: str,
    max_chars: int,
    caller: Any,
) -> tuple[dict[str, Any], Any]:
    items = resolve_references(step.get("items"), previous)
    if not isinstance(items, list):
        raise TypeError("foreach items must resolve to a list")
    if len(items) > 50:
        raise ValueError("foreach accepts at most 50 items")
    execution = str(step.get("execution") or "sequential").casefold()
    if execution not in {"sequential", "parallel"}:
        raise ValueError("foreach execution must be sequential or parallel")
    if execution == "parallel" and not spec.parallel_safe:
        raise ValueError("parallel foreach requires a read-only batch-safe operation")
    per_item_budget = max(400, min(4_000, max_chars // max(1, len(items))))

    async def run(item: Any) -> tuple[dict[str, Any], Any]:
        arguments = resolve_references(
            dict(step.get("arguments") or {}), previous, item=item
        )
        return await _execute(
            spec,
            arguments,
            unity_instance=unity_instance,
            output_mode=output_mode,
            max_chars=per_item_budget,
            caller=caller if execution == "sequential" else None,
        )

    results: list[tuple[dict[str, Any], Any]] = []
    if execution == "parallel":
        results = list(await asyncio.gather(*(run(item) for item in items)))
    else:
        for item in items:
            result = await run(item)
            results.append(result)
            if bool(step.get("stop_on_error", True)) and not result[0]["ok"]:
                break
    previews = [result for result, _ in results]
    raw = [value for _, value in results]
    ok = len(results) == len(items) and all(result["ok"] for result in previews)
    return {
        "ok": ok,
        "operation": spec.name,
        "execution": execution,
        "completed": len(results),
        "requested": len(items),
        "data": {"items": previews},
    }, raw


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def batch_operations(
    operations: list[dict[str, Any]],
    execution: Literal["sequential", "parallel"] = "sequential",
    stop_on_error: bool = True,
    unity_instance: str | None = None,
    output_mode: Literal["compact", "standard"] = "compact",
    response_mode: Literal["summary", "steps", "emits"] = "summary",
    max_chars: int = 20_000,
    request_id: str | None = None,
) -> ToolResult:
    """Run calls or local select/assert/poll/foreach/emit workflow steps."""
    try:
        if not 1 <= len(operations) <= 50:
            raise ValueError("operations must contain between 1 and 50 steps")
        kinds = [_step_kind(step) for step in operations]
        specs: list[OperationSpec | None] = []
        for kind, step in zip(kinds, operations, strict=True):
            specs.append(
                await _resolve(str(step.get("operation") or ""))
                if kind in {"call", "poll", "foreach"}
                else None
            )
        batch_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "operations": to_jsonable(operations),
                    "execution": execution,
                    "stop_on_error": stop_on_error,
                    "unity_instance": unity_instance,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if request_id:
            prior = store.get_request(request_id, fingerprint=batch_fingerprint)
            if prior is not None:
                raw, info = prior
                repeated = compact_result(
                    {"steps": raw},
                    mode="compact",
                    max_chars=max_chars,
                    result_id=info.result_id,
                    mutating=info.mutating,
                )
                repeated.update(
                    ok=info.ok,
                    execution=execution,
                    response_mode=response_mode,
                    completed=len(raw) if isinstance(raw, list) else None,
                    requested=len(operations),
                    duplicate_suppressed=True,
                    request_id=request_id,
                )
                return _text(repeated)
        if execution == "parallel":
            if any(kind != "call" for kind in kinds):
                raise ValueError("Top-level parallel mode only accepts call steps")
            unsafe = [
                spec.name
                for spec in specs
                if spec is not None and not spec.parallel_safe
            ]
            if unsafe:
                raise ValueError(
                    f"Parallel mode only accepts read-only batch-safe operations: {', '.join(unsafe)}"
                )
            if any(contains_step_reference(step) for step in operations):
                raise ValueError("Parallel steps cannot reference other steps")

        per_step_budget = max(500, min(8_000, max_chars // len(operations)))
        previews: list[dict[str, Any]] = []
        raw_steps: list[Any] = []
        emitted: list[Any] = []

        async def run(index: int) -> tuple[int, dict[str, Any], Any]:
            step = operations[index]
            spec = specs[index]
            assert spec is not None
            result, raw = await _execute(
                spec,
                dict(step.get("arguments") or {}),
                unity_instance=str(step.get("unity_instance") or unity_instance or "")
                or None,
                output_mode=output_mode,
                max_chars=per_step_budget,
            )
            return index, result, raw

        if execution == "parallel":
            completed = await asyncio.gather(
                *(run(index) for index in range(len(operations)))
            )
            for _, result, raw in sorted(completed):
                previews.append(result)
                raw_steps.append(raw)
        else:
            async with _batch_caller(
                reuse=all(spec is None or not spec.mutating for spec in specs)
            ) as caller:
                for index, step in enumerate(operations):
                    kind = kinds[index]
                    step_instance = (
                        str(step.get("unity_instance") or unity_instance or "") or None
                    )
                    when = step.get("when")
                    if when is not None and not evaluate_condition(when, raw_steps):
                        raw = {"skipped": True}
                        result = {"ok": True, "skipped": True, "data": raw}
                    elif kind == "call":
                        spec = specs[index]
                        assert spec is not None
                        arguments = resolve_references(
                            dict(step.get("arguments") or {}), raw_steps
                        )
                        result, raw = await _execute(
                            spec,
                            arguments,
                            unity_instance=step_instance,
                            output_mode=output_mode,
                            max_chars=per_step_budget,
                            caller=caller,
                        )
                    elif kind == "poll":
                        spec = specs[index]
                        assert spec is not None
                        result, raw = await _poll_step(
                            step,
                            spec,
                            raw_steps,
                            unity_instance=step_instance,
                            output_mode=output_mode,
                            max_chars=per_step_budget,
                            caller=caller,
                        )
                    elif kind == "foreach":
                        spec = specs[index]
                        assert spec is not None
                        result, raw = await _foreach_step(
                            step,
                            spec,
                            raw_steps,
                            unity_instance=step_instance,
                            output_mode=output_mode,
                            max_chars=per_step_budget,
                            caller=caller,
                        )
                    elif kind == "select":
                        source = resolve_references(step.get("from"), raw_steps)
                        raw = select_value(
                            source,
                            path=str(step.get("path") or ""),
                            where=step.get("where"),
                            fields=step.get("fields"),
                            sort_by=step.get("sort_by"),
                            descending=bool(step.get("descending", False)),
                            limit=int(step.get("limit") or 50),
                            aggregate=step.get("aggregate"),
                            steps=raw_steps,
                        )
                        result = {"ok": True, "data": raw}
                    elif kind == "assert":
                        condition = step.get("condition")
                        passed = evaluate_condition(condition, raw_steps)
                        raw = {"passed": passed}
                        result = {
                            "ok": passed,
                            "data": raw,
                            **(
                                {
                                    "error": str(
                                        step.get("message") or "assertion failed"
                                    )
                                }
                                if not passed
                                else {}
                            ),
                        }
                    else:
                        raw = resolve_references(step.get("value"), raw_steps)
                        emitted.append(raw)
                        result = {"ok": True, "data": raw}

                    previews.append(result)
                    raw_steps.append(raw)
                    if stop_on_error and not result["ok"]:
                        break

        batch_ok = all(step["ok"] for step in previews) and len(previews) == len(
            operations
        )
        info = store.put(
            raw_steps,
            operation="batch",
            mutating=any(spec is not None and spec.mutating for spec in specs),
            ok=batch_ok,
        )
        if response_mode == "steps":
            visible: Any = {"steps": previews, "emits": emitted}
        elif response_mode == "emits":
            visible = {
                "emits": emitted,
                "failures": [
                    _receipt(index, kinds[index], result)
                    for index, result in enumerate(previews)
                    if not result["ok"]
                ],
            }
        else:
            visible = {
                "steps": [
                    _receipt(index, kinds[index], result)
                    for index, result in enumerate(previews)
                ],
                **({"emits": emitted} if emitted else {}),
            }
        response = compact_result(
            visible,
            mode=output_mode,
            max_chars=max_chars,
            result_id=info.result_id,
            mutating=any(spec is not None and spec.mutating for spec in specs),
        )
        response.update(
            ok=batch_ok,
            execution=execution,
            response_mode=response_mode,
            completed=len(previews),
            requested=len(operations),
        )
        if request_id:
            store.remember_request(
                request_id,
                fingerprint=batch_fingerprint,
                result_id=info.result_id,
            )
            response["request_id"] = request_id
        return _text(response)
    except Exception as exc:
        return _text({"ok": False, "error": str(exc)})


async def _safe_resource(uri: str) -> Any:
    try:
        return await backend.read_resource(uri)
    except Exception as exc:
        return {"error": str(exc), "uri": uri}


def _collect_ids(value: Any) -> list[int]:
    found: list[int] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in {"instanceid", "instance_id", "id"}:
                try:
                    found.append(int(item))
                except (TypeError, ValueError):
                    pass
            found.extend(_collect_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_ids(item))
    return list(dict.fromkeys(found))


_VOLATILE_REVISION_KEYS = {
    "age_ms",
    "observed_at_unix_ms",
    "sequence",
    "since_unix_ms",
    "time",
    "timestamp",
}


def _stable_revision_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_revision_data(item)
            for key, item in value.items()
            if key.casefold() not in _VOLATILE_REVISION_KEYS
        }
    if isinstance(value, list):
        return [_stable_revision_data(item) for item in value]
    return value


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def inspect_unity(
    scope: Literal["state", "project", "scene", "console", "objects"] = "state",
    targets: list[str | int] | None = None,
    detail: Literal["low", "standard", "full"] = "standard",
    since_revision: str | None = None,
    unity_instance: str | None = None,
    max_chars: int = 12_000,
) -> ToolResult:
    """Inspect Unity semantically; unchanged revisions return no repeated payload."""
    try:
        preview: Any | None = None
        inspection_ok = True
        if scope == "state":
            raw = await _safe_resource("mcpforunity://editor/state")
            inspection_ok = _data_is_ok(raw)
        elif scope == "project":
            raw = await _safe_resource("mcpforunity://project/info")
            inspection_ok = _data_is_ok(raw)
        elif scope == "console":
            result = await backend.call(
                "read_console",
                {
                    "action": "get",
                    "types": ["error", "warning"],
                    "count": 30,
                    "format": "plain",
                    "include_stacktrace": detail == "full",
                    **({"unity_instance": unity_instance} if unity_instance else {}),
                },
            )
            raw = result.data
            inspection_ok = _is_ok(result)
        elif scope == "scene":
            suffix = {
                "low": {"page_size": 25, "max_depth": 2},
                "standard": {"page_size": 75},
                "full": {"page_size": 200, "include_transform": True},
            }[detail]
            common = {"unity_instance": unity_instance} if unity_instance else {}
            active, hierarchy = await asyncio.gather(
                backend.call("manage_scene", {"action": "get_active", **common}),
                backend.call(
                    "manage_scene", {"action": "get_hierarchy", **suffix, **common}
                ),
            )
            raw = {"active": active.data, "hierarchy": hierarchy.data}
            inspection_ok = _is_ok(active) and _is_ok(hierarchy)
            preview = {
                "active": prepare_preview("scene.get_active", active.data),
                "hierarchy": prepare_preview("scene.get_hierarchy", hierarchy.data),
            }
        else:
            if not targets:
                raise ValueError("targets are required for objects scope")
            ids: list[int] = []
            searches: dict[str, Any] = {}
            for target in targets[:20]:
                try:
                    ids.append(int(target))
                except (TypeError, ValueError):
                    found = await backend.call(
                        "find_gameobjects",
                        {
                            "search_term": str(target),
                            "search_method": "by_name",
                            "page_size": 10,
                            **(
                                {"unity_instance": unity_instance}
                                if unity_instance
                                else {}
                            ),
                        },
                    )
                    searches[str(target)] = found.data
                    inspection_ok = inspection_ok and _is_ok(found)
                    ids.extend(_collect_ids(found.data))
            ids = list(dict.fromkeys(ids))[:50]
            uris = [f"mcpforunity://scene/gameobject/{item}" for item in ids]
            if detail != "low":
                uris += [
                    f"mcpforunity://scene/gameobject/{item}/components" for item in ids
                ]
            resources = await asyncio.gather(*(_safe_resource(uri) for uri in uris))
            inspection_ok = inspection_ok and all(
                _data_is_ok(item) for item in resources
            )
            raw = {
                "resolved_ids": ids,
                "searches": searches,
                "resources": dict(zip(uris, resources)),
            }

        canonical = json.dumps(
            _stable_revision_data(raw),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        if inspection_ok and since_revision and since_revision == revision:
            return _text(
                {"ok": True, "scope": scope, "revision": revision, "unchanged": True}
            )
        info = store.put(
            raw, operation=f"inspect.{scope}", mutating=False, ok=inspection_ok
        )
        if preview is None:
            preview = prepare_preview(
                "console.get" if scope == "console" else f"inspect.{scope}", raw
            )
        response = compact_result(
            preview,
            mode={"low": "compact", "standard": "standard", "full": "full"}[detail],
            max_chars=max_chars,
            result_id=info.result_id,
        )
        response.update(
            ok=inspection_ok, scope=scope, revision=revision, unchanged=False
        )
        if not inspection_ok:
            reason = _failure_reason(raw)
            if reason:
                response["reason"] = reason
                if _is_transient_reason(reason):
                    response.update(
                        retryable=True, retry_after_ms=1_000, retry_safe=True
                    )
        return _text(response)
    except Exception as exc:
        return _text({"ok": False, "scope": scope, "error": str(exc)})


@mcp.tool(
    output_schema=None,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_viewport(
    source: Literal["scene_view", "game_view"] = "scene_view",
    max_resolution: int = 512,
    target: str | int | list[float] | None = None,
    unity_instance: str | None = None,
) -> ToolResult:
    """Return one bounded inline viewport image for visual verification."""
    try:
        arguments: dict[str, Any] = {
            "action": "screenshot",
            "capture_source": source,
            "include_image": True,
            "max_resolution": max(128, min(int(max_resolution), 1024)),
        }
        if target is not None:
            arguments["view_target"] = target
        if unity_instance:
            arguments["unity_instance"] = unity_instance
        result = await backend.call("manage_camera", arguments)
        if not _is_ok(result):
            raw = to_jsonable(result.data)
            info = store.put(
                raw, operation="camera.screenshot", mutating=False, ok=False
            )
            failure: dict[str, Any] = {
                "ok": False,
                "error": _fallback_preview(raw),
                "result_id": info.result_id,
            }
            reason = _failure_reason(raw)
            if reason:
                failure["reason"] = reason
                if _is_transient_reason(reason):
                    failure.update(
                        retryable=True, retry_after_ms=1_000, retry_safe=True
                    )
            return _text(failure)
        return ToolResult(content=result.content, structured_content=None)
    except Exception as exc:
        return _text({"ok": False, "error": str(exc)})


def main() -> None:
    transport = os.getenv("UNITY_MCP_EFFICIENT_TRANSPORT", "stdio")
    if transport not in {"stdio", "http", "sse"}:
        raise ValueError("UNITY_MCP_EFFICIENT_TRANSPORT must be stdio, http, or sse")
    mcp.run(transport=transport, show_banner=False)


if __name__ == "__main__":
    main()
