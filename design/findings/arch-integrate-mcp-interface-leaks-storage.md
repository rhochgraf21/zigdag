---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.integrate.mcp
digest: bb0254875a01
evidence: "server(project: Path) -> MCPServer"
hint: Keep serve(project) as the only public entry point, or return an arch-owned handle that offers just what callers need (for example, its tool names for tests).
---
The part claims to hide the MCP protocol, yet its public function returns the MCP library's server object. Every caller is therefore tied to that library and its version.
