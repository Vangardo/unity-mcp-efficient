# Efficient facade API

The facade intentionally exposes six stable tools. The larger upstream tool catalog is indexed inside the server and retrieved only by search.

## `search_capabilities`

Search with a task phrase, not a guessed endpoint. Results contain exact `operation` names, mutation and batching flags, required arguments, and optionally compact schema hints.

Ranking combines exact action/name matches, multilingual normalization, BM25-style relevance, aliases, category penalties, and typo tolerance. It does not call another language model. Action schemas are narrowed from a manager's universal argument union to the selected action contract.

- Empty query: list categories and counts.
- `include_schema=false`: cheapest discovery pass.
- `include_schema=true`: use after narrowing to an operation.
- `refresh=true`: rebuild the index after upstream tools or Unity packages change.

## `call_operation`

Executes one exact operation. Arguments omit the upstream `action`; the facade injects it. The response contains `ok`, `operation`, bounded `data`, and `meta.result_id` for the untouched raw result. `meta.recovery` appears when content was omitted.

Set `request_id` for mutations. The identifier must be unique to one intended operation and argument set. Repeating the same request returns the stored result with `duplicate_suppressed=true`; reusing the identifier with different arguments is rejected before Unity is called. This protects normal retries after a returned response, but no facade can prove exactly-once execution if the process dies between Unity accepting a command and its receipt being committed.

Typed FastMCP/Pydantic results are normalized before storage and rendering. The raw result is stored before preview generation, so a postprocessing failure still returns a recoverable `result_id`. Upstream `success=false` always makes the outer `ok=false`.

Transient reload states include `no_unity_session`, `stale_connection`, and `stale_status`. They return `retryable`, `retry_after_ms`, and `retry_safe`. Never replay a mutation when `retry_safe=false`; inspect state after the delay instead.

`stale_status` means the cached editor telemetry has not caught up yet; it is not proof that Unity is stuck. Wait once, re-inspect with `since_revision`, and avoid broad status loops. Likewise, `is_changing` can lag behind an otherwise ready editor. When compilation and asset updating are false and revision plus relevant state remain stable across two delayed checks, treat `is_changing` as advisory and verify the intended result directly.

Async start operations such as `tests.run` return a compact polling contract containing `job_id`, status, and mode while retaining the complete raw envelope under `meta.result_id`.

Unity-aware defaults cap console, hierarchy, asset-search, test, and screenshot payloads. Explicit arguments override defaults.

Search results describe supported facade contracts, including optional integrations; they do not guarantee that every optional Unity backend is installed. In particular, a Roslyn operation can be discoverable while Roslyn is unavailable in the project. Treat the backend error as decisive and use the normal script-edit, refresh, and compact-console workflow rather than retrying the optional path.

## `get_result`

Reads stored raw data without executing Unity again. Results expire after 30 minutes by default. The normal installation uses a bounded local SQLite store, so handles and request receipts survive facade restarts. Set `UNITY_MCP_RESULT_DB=memory` to disable persistence or provide a path to relocate it.

- `path`: RFC 6901 JSON Pointer, for example `/data/items/0`.
- `offset` and `limit`: page arrays, object keys, or text lines.
- `pattern`: case-insensitive matching over rendered JSON lines.
- `output_mode`: use `standard`, then `full` only for a narrow selection.

## `batch_operations`

Accepts 1-50 backward-compatible `{operation, arguments}` call steps plus deterministic workflow steps. Sequential steps can use exact whole-value references such as `$steps.0.data.id`. References resolve against raw step results, not compact previews.

Parallel mode accepts only operations classified read-only and batch-safe. It rejects mutations, polling/build operations, and inter-step references before execution. Each step receives a share of the total output budget; raw step outputs remain retrievable.

- `response_mode=summary` returns small receipts and explicit emits (default).
- `response_mode=emits` returns only emitted values and failures.
- `response_mode=steps` returns compact per-step previews for debugging.
- A top-level `request_id` deduplicates an exact workflow, including mutating batches.

Read [workflows.md](workflows.md) for the bounded workflow grammar. The runtime never evaluates caller code.

## `inspect_unity`

Semantic scopes are `state`, `project`, `scene`, `console`, and `objects`. `detail=low` is the normal starting point. The response includes a content revision. Passing it as `since_revision` suppresses unchanged payloads.

Object inspection accepts names or instance IDs. Names are resolved first; component resources are fetched only at `standard` or `full` detail.

## `get_viewport`

Returns one inline image without encoding the same image into structured JSON. Sources are `scene_view` and `game_view`; resolution is clamped to 128-1024.

The captured render target may omit IMGUI and editor overlays. A viewport image is therefore evidence about rendered Scene/Game content, not proof of IMGUI presence or absence. Use behavior, state/logs, or a permitted desktop screenshot when UI-overlay verification is material.
