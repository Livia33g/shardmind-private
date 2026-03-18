"""MCP stdio bridge."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from shardmind.bootstrap import build_runtime
from shardmind.mcp.tools import KnowledgeTools

MCP_TOOL_NAMES = {
    "create_note": "knowledge_create_note",
    "create_paper_card": "knowledge_create_paper_card",
    "append_to_note": "knowledge_append_to_note",
    "enrich_paper_card": "knowledge_enrich_paper_card",
    "get_object": "knowledge_get_object",
    "list_objects": "knowledge_list_objects",
    "search": "knowledge_search",
}


def register_tools(server: FastMCP, tools: KnowledgeTools) -> FastMCP:
    """Register the current MCP tool surface onto a FastMCP server."""

    @server.tool(name=MCP_TOOL_NAMES["create_note"])
    def create_note(payload: dict) -> dict:
        return tools.create_note(payload)

    @server.tool(name=MCP_TOOL_NAMES["create_paper_card"])
    def create_paper_card(payload: dict) -> dict:
        return tools.create_paper_card(payload)

    @server.tool(name=MCP_TOOL_NAMES["append_to_note"])
    def append_to_note(payload: dict) -> dict:
        return tools.append_to_note(payload)

    @server.tool(name=MCP_TOOL_NAMES["enrich_paper_card"])
    def enrich_paper_card(payload: dict) -> dict:
        return tools.enrich_paper_card(payload)

    @server.tool(name=MCP_TOOL_NAMES["get_object"])
    def get_object(payload: dict) -> dict:
        return tools.get_object(payload)

    @server.tool(name=MCP_TOOL_NAMES["list_objects"])
    def list_objects(payload: dict) -> dict:
        return tools.list_objects(payload)

    @server.tool(name=MCP_TOOL_NAMES["search"])
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
