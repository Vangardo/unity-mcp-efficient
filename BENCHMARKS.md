# Benchmarks

The benchmark scripts are small enough to audit. They measure model-visible JSON and deterministic search behavior; they do not estimate time saved, model quality, or API cost.

## Baseline

- Date: 2026-08-24
- Upstream: [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) `v10.1.0`
- Upstream commit: `c14de1e6dc01ab42d2bb358730cff954bce0ce6b`
- Facade version: `0.2.0`
- Python: 3.11
- FastMCP: 3.4.7
- MCP Python SDK: 1.29.0

## Tool surface

`benchmarks/measure_surface.py` serializes each model-visible tool as `name`, `description`, and `inputSchema` using compact JSON.

```json
{
  "upstream_tool_count": 48,
  "efficient_tool_count": 6,
  "upstream_chars": 93119,
  "efficient_chars": 3657,
  "reduction_percent": 96.07
}
```

The approximate token column in the README divides character count by four and rounds up. The estimate is a comparison aid, not a tokenizer result.

## Synthetic hierarchy

The same script builds 250 synthetic objects. Each object includes metadata, two component names, and 300 vertex indices. The legacy side counts the same compact JSON in text and structured payloads. The efficient side runs the hierarchy post-processor and response compactor with an 8,000-character budget.

```json
{
  "objects": 250,
  "vertices_per_object": 300,
  "legacy_text_plus_structured_chars": 628110,
  "efficient_preview_chars": 875,
  "reduction_percent": 99.86
}
```

This test isolates a failure mode: large geometry arrays entering model context when the task needs hierarchy structure. It does not represent every Unity response.

## Catalog and search

`benchmarks/evaluate_facade.py` builds the live action catalog from the upstream schemas.

```json
{
  "upstream_tools": 48,
  "indexed_operations": 377,
  "union_argument_fields": 5566,
  "action_argument_fields": 1798,
  "argument_reduction_percent": 67.70,
  "average_optional_arguments_per_action": 4.42,
  "maximum_optional_arguments_per_action": 16,
  "search_cases": 15,
  "recall_at_1": 1.0,
  "recall_at_3": 1.0
}
```

The 15 search cases cover English and Russian phrases for GameObjects, tests, refresh and compilation, Play Mode, console output, screenshots, hierarchy, ProBuilder, physics, VFX, and builds. This is a regression suite, not a statistically broad retrieval evaluation.

## Reproduce

Start MCP for Unity in HTTP mode. Set `UNITY_MCP_BACKEND_URL` when the endpoint uses a port other than 8080, then run:

```bash
uv sync --extra dev
uv run pytest -q
uv run python benchmarks/evaluate_facade.py
uv run python benchmarks/measure_surface.py
uv run python benchmarks/live_smoke.py
```

Record the upstream version and commit whenever publishing new numbers. Do not compare results produced from different upstream catalogs without saying so.

## Live smoke

`benchmarks/live_smoke.py` checks the connection without mutating the project. For the baseline above it confirmed:

```json
{
  "tool_count": 6,
  "search_rank_1": "editor.refresh",
  "state_ok": true,
  "scene_batch_ok": true,
  "scene_steps_completed": 2
}
```

The script retries transient missing-session and stale-status responses at most three times using the facade's `retry_after_ms` signal. The smoke test fails rather than hiding a persistent Unity connection problem.
