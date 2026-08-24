# Third-party software

This repository does not vendor third-party runtime source code. Package installers resolve dependencies separately under their own licenses.

Direct runtime dependencies:

| Project | Use | License | Source |
|---|---|---|---|
| FastMCP | MCP client and facade server runtime | Apache License 2.0 | [PrefectHQ/fastmcp](https://github.com/PrefectHQ/fastmcp) |
| MCP Python SDK | MCP protocol types and transport support | MIT License | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) |

External compatibility backend:

| Project | Use | License | Source |
|---|---|---|---|
| MCP for Unity | Unity Editor bridge and upstream tool implementation | MIT License | [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) |

Development and test dependencies are listed in `pyproject.toml` and are installed separately. Their package distributions contain the applicable license metadata and notices.
