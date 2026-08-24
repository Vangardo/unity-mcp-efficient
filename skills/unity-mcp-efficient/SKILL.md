---
name: unity-mcp-efficient
description: Control and inspect Unity Editor through the token-efficient Unity MCP facade. Use for Unity scene work, GameObjects, components, ProBuilder modeling, assets, C# scripts, console diagnostics, tests, builds, profiling, screenshots, or MCP troubleshooting when compact context, bulk execution, and recoverable outputs matter.
---

# Unity MCP Efficient

Use the six facade tools instead of loading or calling the upstream Unity tools directly.

## Core loop

1. Call `inspect_unity(scope="state", detail="low")` before a multi-step change. If Unity is compiling, re-inspect with `since_revision` rather than fetching broad state repeatedly.
2. Call `search_capabilities` with a short task phrase. Set `include_schema=true` only for the selected operation when its arguments are unclear.
3. Prefer `batch_operations` when two or more calls are already known:
   - Use `sequential` for mutations and dependencies.
   - Reference earlier raw data with exact values such as `$steps.0.data.instanceID`.
   - Use `parallel` only for independent read-only operations; the server rejects unsafe parallel work.
   - Use local `select`, `assert`, `foreach`, `poll`, and `emit` steps when they avoid intermediate model turns. Default to `response_mode="summary"`; use `emits` when only explicit outputs matter.
4. Keep `output_mode="compact"`. When `meta.truncated` is true, use `get_result` with `path`, pagination, or `pattern`; never repeat a mutation to retrieve more output.
5. Verify semantic changes with `inspect_unity`. Use `get_viewport(max_resolution=512)` only when visual evidence materially helps.
6. For asynchronous starts such as `tests.run`, keep the returned `job_id` and poll the matching result operation. Do not start a second job to recover a lost response.

## Context rules

- Inspect `scene` for hierarchy and `objects` for selected targets. Do not request full components or geometry before they are needed.
- Read console errors and warnings without stack traces first. Expand only the failing entry from its stored result.
- For ProBuilder, inspect mesh `summary`; request faces or edges only immediately before an index-based edit.
- After script edits, wait until compilation settles, inspect console errors, then attach or use the component.
- Search again when an operation name is uncertain. Do not guess upstream tool names or actions.
- Search accepts ordinary English or Russian task phrases and common typos. Prefer one concrete intent per query.
- Keep screenshots at 256-512 px during iteration; use 1024 only for a final visual check that needs detail.

## Unity-specific caveats

- Treat `stale_status` and a lingering `is_changing` as advisory telemetry. Use delayed, revision-aware reads and stop polling when compilation, updating, revision, and relevant state are stable.
- Discovery does not prove an optional backend such as Roslyn is installed, and `get_viewport` does not prove IMGUI state. Use the fallback and verification rules in [efficient-api.md](references/efficient-api.md) only when either case occurs.

## Bulk design

Group operations by intent: create objects, configure components, then verify. A sequential batch is one model round trip and preserves step order. Parallel mode is for independent reads such as project, profiler, package, or object queries—not Unity mutations. Use one stable, task-scoped `request_id` for each intended mutation or mutating batch; reuse it only to recover the exact same request after an interrupted response.

## Failures

Treat `ok=false` as a real failure even when the MCP transport succeeded. Preserve the returned operation and result handle. Fix the smallest failed step; do not replay successful mutations.

For `retryable=true`, wait at least `retry_after_ms` before checking again. Repeat only read-only checks when `retry_safe=true`. If `state_may_have_changed=true` or `retry_safe=false`, inspect Unity state instead of replaying the mutation; domain reload may have disconnected MCP after Unity accepted the command.

Read [efficient-api.md](references/efficient-api.md) for exact facade behavior. Read [architecture.md](references/architecture.md) only when installing, benchmarking, or troubleshooting the facade/backend boundary.
Read [workflows.md](references/workflows.md) when a task benefits from filtering, loops, assertions, polling, or output projection inside one batch.
