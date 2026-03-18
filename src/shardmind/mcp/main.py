"""MCP stdio bridge."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from shardmind.bootstrap import build_runtime
from shardmind.mcp.tools import KnowledgeTools


def register_tools(server: FastMCP, tools: KnowledgeTools) -> FastMCP:
    """Register the current MCP tool surface onto a FastMCP server."""

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

    return server


def run_server(tools: KnowledgeTools) -> int:
    server = register_tools(FastMCP("ShardMind"), tools)
    server.run()
    return 0


def main() -> int:
    runtime = build_runtime()
    return run_server(runtime.tools)
