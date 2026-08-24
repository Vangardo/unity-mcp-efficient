# Unity MCP Efficient

[![CI](https://github.com/Vangardo/unity-mcp-efficient/actions/workflows/ci.yml/badge.svg)](https://github.com/Vangardo/unity-mcp-efficient/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An independent, token-efficient MCP facade and Codex skill for [MCP for Unity](https://github.com/CoplayDev/unity-mcp).

It keeps the full Unity feature set behind a small model-facing API. The model sees six stable tools, searches the upstream catalog on demand, receives compact Unity-aware responses, and can chain routine work without bringing every intermediate result into the conversation.

> [!IMPORTANT]
> This project does not replace the Unity package or its Python server. MCP for Unity remains the backend. Register the facade, not the upstream server, with the AI client. Exposing both tool surfaces removes most of the context savings.

## Measured context reduction

On 2026-08-24, the scripts in [`benchmarks/`](benchmarks/) produced these results against MCP for Unity `v10.1.0` (`c14de1e6`).

| Measurement | Upstream surface | Efficient facade | Reduction |
|---|---:|---:|---:|
| Model-visible tools | 48 | 6 | 87.50% |
| Serialized tool schemas | 93,119 chars | 3,657 chars | 96.07% |
| Approximate schema tokens¹ | 23,280 | 915 | 96.07% |
| Synthetic 250-object hierarchy² | 628,110 chars | 875 chars | 99.86% |
| Approximate hierarchy tokens¹ | 157,028 | 219 | 99.86% |
| Action argument surface | 5,566 fields | 1,798 fields | 67.70% |

The dynamic catalog indexed 377 Unity operations. A small deterministic English/Russian search suite returned the expected operation at rank 1 for all 15 cases and within the top 3 for all 15 cases. The release candidate passes 35 facade tests. A live smoke test made no project changes and verified the six-tool surface, `editor.refresh` at rank 1, editor state, and a two-step scene inspection batch against an open Unity Editor.

¹ Token counts use a transparent four-characters-per-token estimate. They describe context footprint, not API billing. Actual tokenization varies by model and payload.

² The hierarchy benchmark models a noisy response containing 250 objects, 300 vertex indices per object, and the same data in text and structured payloads. This stress case does not promise the same reduction for every scene. See [BENCHMARKS.md](BENCHMARKS.md) for the method and raw values.

## What the six tools do

| Tool | Purpose |
|---|---|
| `search_capabilities` | Finds the best Unity operations from a short English or Russian task phrase. Full schemas are optional. |
| `call_operation` | Executes one exact operation and returns a bounded preview plus a recoverable result handle. |
| `batch_operations` | Runs up to 50 bounded call, select, assert, poll, foreach, and emit steps in one model round trip. |
| `inspect_unity` | Reads project, editor, scene, console, or selected-object state with revision-aware suppression. |
| `get_result` | Pages, filters, searches, or selects data already produced without repeating Unity work. |
| `get_viewport` | Returns one bounded Scene or Game view image without duplicating it in structured JSON. |

The model still reaches the 377 indexed operations behind the facade. Those operations no longer occupy the prompt all at once.

## Problems handled at the boundary

| Common failure mode | What the facade changes |
|---|---|
| The client sends dozens of large tool schemas before useful work begins | A six-tool surface with on-demand operation discovery |
| Manager tools expose one large union of arguments for every action | Action-specific schemas; 67.70% fewer argument fields in the measured catalog |
| Scene, console, test, and asset responses flood the conversation | Unity-aware post-processing, strict output budgets, pagination, and result handles |
| A FastMCP or Pydantic `Root` object fails JSON serialization | Recursive JSON normalization before preview construction |
| Unity completes a mutation but disconnects during domain reload | Raw result persistence, explicit retry metadata, and no automatic mutation replay |
| A test run starts but its large envelope hides or loses `job_id` | A compact asynchronous receipt designed for polling |
| The upstream response nests `success: false` under transport-level success | Outer `ok` reflects the nested Unity result |
| Repeating a timed-out mutation may duplicate work | Stable `request_id` receipts suppress exact retries |
| Multi-object work burns one model turn per operation | Bounded sequential workflows and conservative parallel batches for reads |
| `stale_status` or `is_changing` causes open-ended polling | Delayed, revision-aware checks with a clear stopping rule |

## Architecture

```text
Codex or another MCP client
        |
        | sees 6 tools
        v
Unity MCP Efficient (stdio by default)
        |-- capability search over the live upstream catalog
        |-- compact Unity-specific post-processing
        |-- bounded workflow runtime
        |-- local SQLite result and request receipts
        |
        | HTTP, default http://127.0.0.1:8080/mcp
        v
MCP for Unity server
        |
        v
Unity Editor package
```

A skill alone cannot hide tool schemas that an MCP client has already loaded. That is why this repository contains both pieces:

- the facade enforces the smaller API and compact responses;
- the skill teaches Codex how to search, batch, recover, and verify efficiently.

## Install

### 1. Start MCP for Unity in HTTP mode

Install [CoplayDev/MCP for Unity](https://github.com/CoplayDev/unity-mcp) using its upstream instructions. In Unity, open **Window → MCP for Unity**, select the local HTTP transport, and start the server.

The upstream default endpoint is:

```text
http://127.0.0.1:8080/mcp
```

If your project uses another port, pass it through `UNITY_MCP_BACKEND_URL` below.

### 2. Register the facade in Codex

Install [uv](https://docs.astral.sh/uv/) when needed, then run:

```bash
codex mcp add unity-efficient \
  --env UNITY_MCP_BACKEND_URL=http://127.0.0.1:8080/mcp \
  -- uvx --from git+https://github.com/Vangardo/unity-mcp-efficient.git unity-mcp-efficient
```

On PowerShell, use the same command on one line:

```powershell
codex mcp add unity-efficient --env UNITY_MCP_BACKEND_URL=http://127.0.0.1:8080/mcp -- uvx --from git+https://github.com/Vangardo/unity-mcp-efficient.git unity-mcp-efficient
```

Remove or disable any direct MCP for Unity entry from the same Codex client. Keep the upstream HTTP server running, but do not register its 48-tool surface with the model.

### 3. Install the Codex skill

The easiest route is to ask Codex:

```text
$skill-installer Install the skill from https://github.com/Vangardo/unity-mcp-efficient/tree/main/skills/unity-mcp-efficient
```

For a manual user-level install, clone the repository and copy `skills/unity-mcp-efficient` to:

```text
$HOME/.agents/skills/unity-mcp-efficient
```

Codex detects skill changes automatically. Restart it if the skill does not appear.

### Other MCP clients

Use this stdio configuration shape:

```json
{
  "mcpServers": {
    "unity-efficient": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Vangardo/unity-mcp-efficient.git",
        "unity-mcp-efficient"
      ],
      "env": {
        "UNITY_MCP_BACKEND_URL": "http://127.0.0.1:8080/mcp"
      }
    }
  }
}
```

Install the packaged skill when the client supports the Agent Skills format. The facade works without it, but the skill improves tool selection and recovery behavior.

## Recommended agent loop

1. Inspect low-detail Unity state once.
2. Search with one concrete task phrase.
3. Request the selected schema when its arguments are unclear.
4. Batch known dependent work sequentially. Parallelize independent reads, never Unity mutations.
5. Keep compact output and expand stored results by path or page.
6. Verify the semantic result, not every raw intermediate object.

This loop is already encoded in [`skills/unity-mcp-efficient/SKILL.md`](skills/unity-mcp-efficient/SKILL.md).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `UNITY_MCP_BACKEND_URL` | `http://127.0.0.1:8080/mcp` | Upstream MCP for Unity HTTP endpoint |
| `UNITY_MCP_OPERATION_TIMEOUT` | `60` | Per-operation timeout in seconds |
| `UNITY_MCP_RESULT_DB` | OS user cache directory | SQLite result store path; use `memory` for process-local storage |
| `UNITY_MCP_EFFICIENT_TRANSPORT` | `stdio` | Facade transport: `stdio`, `http`, or `sse` |

Keep the default stdio transport unless you have a reason to expose the facade over a network. Read [SECURITY.md](SECURITY.md) before using HTTP or SSE.

## Development and verification

```bash
git clone https://github.com/Vangardo/unity-mcp-efficient.git
cd unity-mcp-efficient
uv sync --extra dev
uv run pytest -q
```

With the upstream HTTP server running:

```bash
uv run python benchmarks/evaluate_facade.py
uv run python benchmarks/measure_surface.py
uv run python benchmarks/live_smoke.py
```

`evaluate_facade.py` and `measure_surface.py` read the live upstream catalog. `live_smoke.py` makes no mutations, but it requires an open and connected Unity Editor.

## Known boundaries

- Compact output is intentionally lossy. The untouched raw result remains available through `get_result` for a bounded time.
- The facade does not make arbitrary Unity mutations safe. Permissions and review still belong to the MCP client and user.
- Parallel mode is conservative. Unity may serialize editor work internally.
- A discoverable optional capability, such as Roslyn support, may still be absent from a particular Unity project.
- Scene and Game view capture may omit IMGUI or editor overlays.
- Compatibility tests use MCP for Unity `v10.1.0`. The catalog is dynamic; benchmark later upstream releases before claiming support.

## Design lineage

We took the progressive-disclosure idea from work on [Vangardo/mcp_hub](https://github.com/Vangardo/mcp_hub), a broader MCP gateway that routes a large integration catalog through a small search-and-call surface. Unity MCP Efficient applies that context discipline to Unity, then adds Unity-specific compaction, revision checks, mutation recovery, screenshots, and bounded local workflows.

If you need this pattern for Slack, Teamwork, Telegram, calendar, memory, automation, or cross-service agents, see [MCP Hub](https://github.com/Vangardo/mcp_hub).

The Unity compatibility backend is [CoplayDev/MCP for Unity](https://github.com/CoplayDev/unity-mcp), distributed under the MIT License. This repository is an independent project and does not include its source code. See [NOTICE.md](NOTICE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License and trademarks

The original code in this repository is available under the [MIT License](LICENSE).

Unity is a trademark or registered trademark of Unity Technologies or its affiliates in the United States and elsewhere. This project is not affiliated with or endorsed by Unity Technologies or CoplayDev. Other names and brands belong to their respective owners.
