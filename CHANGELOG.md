# Changelog

This file records notable changes to Unity MCP Efficient. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-25

First public release.

### Added

- Six-tool MCP facade with on-demand discovery across 377 indexed Unity operations.
- Unity-aware compaction for scene, console, test, asset, and editor responses.
- Recoverable raw-result storage, pagination, filtering, and stable request receipts.
- Bounded batch workflows with conservative parallelism for independent reads.
- Safe normalization of FastMCP and Pydantic results, including `Root` values.
- Explicit handling for nested Unity failures, stale status, domain reloads, and asynchronous test jobs.
- Codex skill with compact operating guidance and task-specific references.
- Reproducible surface, search, hierarchy, and live smoke benchmarks.
- Automated tests and CI for Python 3.10 through 3.13.

[Unreleased]: https://github.com/Vangardo/unity-mcp-efficient/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Vangardo/unity-mcp-efficient/releases/tag/v0.2.0
