# Contributing

Contributions are welcome when they preserve the main contract: a small model-facing surface, bounded output, recoverable raw results, and conservative mutation behavior.

## Development setup

```bash
git clone https://github.com/Vangardo/unity-mcp-efficient.git
cd unity-mcp-efficient
uv sync --extra dev
uv run pytest -q
```

The unit tests use in-process fakes and do not require Unity. Live benchmarks require MCP for Unity in HTTP mode and, for the smoke test, an open Unity Editor.

## Pull requests

- Add focused regression coverage for behavior changes.
- Report any change to the six public tool schemas and include the before/after serialized size.
- Do not expand compact output by default to make a single case easier. Store the raw result and expose a narrow retrieval path instead.
- Never retry mutations automatically.
- Keep optional or tool-specific detail out of `SKILL.md`; put it in a referenced document that Codex loads when relevant.
- Include the upstream MCP for Unity version used for compatibility testing.
- Do not submit Unity assets, proprietary project data, copied documentation, generated credentials, or third-party source without a compatible license and the required notices.

Run the deterministic checks before opening a pull request:

```bash
uv run pytest -q
uv run python benchmarks/evaluate_facade.py
uv run python benchmarks/measure_surface.py
```

The two benchmark scripts require the upstream HTTP endpoint. If the endpoint is unavailable, run the unit tests and state which live checks remain pending.
