# Security policy

## Scope

Unity MCP Efficient forwards operations to MCP for Unity. Depending on the exposed upstream catalog, those operations can edit project files, execute code in the Unity Editor, install packages, delete objects, run builds, or access local project data. The facade reduces context and adds recovery controls. Those controls do not provide a sandbox or authorization system.

## Supported versions

| Version | Security fixes |
|---|---|
| Latest `0.2.x` release | Supported |
| Earlier versions | Upgrade before reporting |

## Safe defaults

- Keep the upstream MCP for Unity server bound to loopback unless you have configured its authentication and network controls.
- Prefer the facade's default stdio transport. Do not expose its HTTP or SSE transport to an untrusted network without an authenticated reverse proxy or comparable protection.
- Register the facade rather than the direct upstream tool surface, but keep client-side approvals enabled for consequential operations.
- Treat `request_id` as replay protection for an exact request, not as a general transaction system.
- The result store may contain scene, console, asset, test, or project metadata. Protect its filesystem location, use `UNITY_MCP_RESULT_DB=memory` when persistence is undesirable, and do not place it in a shared directory.
- Do not put credentials, tokens, or private source code in issue reports or benchmark output.

## Reporting a vulnerability

After the public repository is available, report vulnerabilities through GitHub Security Advisories for `Vangardo/unity-mcp-efficient`. Do not open a public issue for an unpatched vulnerability.

Include the affected version, impact, a minimal reproduction, and whether the issue also affects the upstream MCP for Unity server. Report upstream vulnerabilities through the process documented by CoplayDev as well.
