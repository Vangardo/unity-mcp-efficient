# Publishing checklist

Recommended repository name: `Vangardo/unity-mcp-efficient`.

Suggested GitHub description:

> Independent token-efficient MCP facade and Codex skill for MCP for Unity: 96% smaller tool-schema surface, compact results, bulk workflows, and recoverable operations.

Suggested topics:

`unity`, `mcp`, `codex`, `ai-agents`, `tool-use`, `context-window`, `gamedev`, `fastmcp`, `python`

## Before the first push

- Create an empty public repository named `unity-mcp-efficient` under `Vangardo`. Do not generate another README, license, or `.gitignore` on GitHub.
- Confirm that `Vangardo` is the intended copyright holder and repository owner.
- Check every `Vangardo/unity-mcp-efficient` URL if a different owner or name is chosen.
- Run the unit tests, package build, skill validation, secret scan, link check, and benchmark verification.
- Confirm that no upstream MCP for Unity source, Unity project assets, cache files, databases, credentials, or user-specific paths are tracked.
- Review [NOTICE.md](NOTICE.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and the trademark disclaimer.

## Initial Git commands

Run these only after the GitHub repository exists:

```bash
git init
git branch -M main
git add .
git commit -m "Release Unity MCP Efficient 0.2.0"
git remote add origin https://github.com/Vangardo/unity-mcp-efficient.git
git push -u origin main
```

After CI passes, create a `v0.2.0` release. The benchmark claims in the README are tied to the baseline documented in [BENCHMARKS.md](BENCHMARKS.md).
