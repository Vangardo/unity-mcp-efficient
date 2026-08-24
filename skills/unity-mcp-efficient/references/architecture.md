# Architecture and installation

```text
AI client
  -> Unity MCP Efficient (6 tools, stdio)
       -> dynamic operation catalog
       -> deterministic workflow runtime
       -> Unity-aware response postprocessing
       -> compressed durable TTL/LRU result store
       -> upstream MCP for Unity (HTTP, default 127.0.0.1:8080/mcp)
            -> Unity Editor package
```

The upstream server remains the compatibility and Unity transport layer. The facade changes only what the model sees and receives. This keeps the fork small and lets upstream Unity packages continue to work.

## Run

From `Server`:

```powershell
uv run unity-mcp-efficient
```

The upstream MCP must be available. Override its address with `UNITY_MCP_BACKEND_URL`. Override per-operation timeout with `UNITY_MCP_OPERATION_TIMEOUT`.

Result handles and explicit idempotency receipts are stored under the user's local application-data/cache directory by default. Set `UNITY_MCP_RESULT_DB` to a custom SQLite path, or to `memory` to use process-local storage.

Example MCP client entry (replace the directory):

```json
{
  "mcpServers": {
    "unity-mcp-efficient": {
      "command": "uv",
      "args": ["--directory", "C:/path/to/unity_skill/Server", "run", "unity-mcp-efficient"],
      "env": {"UNITY_MCP_BACKEND_URL": "http://127.0.0.1:8080/mcp"}
    }
  }
}
```

Expose only the efficient facade to the model. The upstream HTTP server is an internal dependency; registering both tool surfaces forfeits most context savings.

## Guarantees and boundaries

- Raw JSON results are compressed and bounded by TTL, item count, and total bytes. The default SQLite store survives facade restarts.
- Compaction is structure-preserving and diagnostic-first, but intentionally lossy.
- Mutations are never automatically retried by the facade.
- Exact retries with an explicit `request_id` are answered from the stored receipt rather than replayed.
- Parallel mode is conservative. Unity itself may serialize editor work.
- Sequential read-only workflows reuse one short backend session. Mutation workflows reconnect conservatively so a Unity domain reload cannot poison later steps.
- The revision mechanism avoids repeated model payloads; it is not yet a Unity-side incremental change journal.
