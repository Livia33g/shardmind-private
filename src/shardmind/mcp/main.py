"""Optional MCP stdio bridge."""

from __future__ import annotations

from shardmind.bootstrap import build_runtime


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - optional integration
        raise SystemExit(
            "The optional 'mcp' package is not installed. "
            "Use the Python tool registry via 'shardmind invoke' or install MCP support."
        ) from exc

    runtime = build_runtime()
    tools = runtime.tools
    server = FastMCP("ShardMind")

    @server.tool(name="knowledge.create_note")
    def create_note(payload: dict) -> dict:
        return tools.create_note(payload)

    @server.tool(name="knowledge.append_to_note")
    def append_to_note(payload: dict) -> dict:
        return tools.append_to_note(payload)

    @server.tool(name="knowledge.get_object")
    def get_object(payload: dict) -> dict:
        return tools.get_object(payload)

    @server.tool(name="knowledge.list_objects")
    def list_objects(payload: dict) -> dict:
        return tools.list_objects(payload)

    @server.tool(name="knowledge.search")
    def search(payload: dict) -> dict:
        return tools.search(payload)

    server.run()
    return 0
