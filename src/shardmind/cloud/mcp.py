"""Cloud-backed MCP server for remote ChatGPT/Gemini connector use."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from shardmind.cloud.main import CloudStore
from shardmind.errors import InvalidInputError, ShardMindError
from shardmind.mcp.main import SERVER_INSTRUCTIONS, _apply_strict_arg_model_config


class CloudMCPTools:
    def __init__(self, cloud_store: CloudStore, account_email: str):
        self.cloud_store = cloud_store
        self.account_email = account_email.strip().lower()

    def search(
        self,
        query: Annotated[str, Field(description="Lexical search query string.")],
        object_types: Annotated[
            list[Literal["note", "paper-card"]] | None,
            Field(description="Optional object-type filter list."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(description="Optional path prefix filter."),
        ] = None,
        top_k: Annotated[
            int,
            Field(ge=1, le=50, description="Maximum number of ranked results to return."),
        ] = 10,
        tags: Annotated[
            list[str] | None,
            Field(description="Optional tag filter; only objects matching these tags are returned."),
        ] = None,
    ) -> dict[str, object]:
        if not query.strip():
            raise InvalidInputError("query must be a non-empty string.")
        return self.cloud_store.search(
            account_email=self.account_email,
            query=query,
            object_types=object_types,
            path_scope=path_scope,
            top_k=top_k,
            tags=tags,
        )

    def fetch(
        self,
        id: Annotated[
            str,
            Field(
                description=(
                    "Object id returned by search or list tools. Use note-... for notes and "
                    "paper-... for paper cards."
                )
            ),
        ],  # noqa: A002
    ) -> dict[str, object]:
        if not id.strip():
            raise InvalidInputError("id must be a non-empty string.")
        return self.cloud_store.fetch(account_email=self.account_email, document_id=id)

    def list_objects(
        self,
        object_type: Annotated[
            Literal["note", "paper-card"] | None,
            Field(description="Optional type filter. Omit to include both object types."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(description="Optional path prefix filter such as notes/inbox or library/papers."),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=200, description="Maximum number of objects to return."),
        ] = 50,
    ) -> dict[str, object]:
        documents = self.cloud_store.account_documents(self.account_email)
        objects = []
        for document in documents:
            if object_type and document.get("type") != object_type:
                continue
            path = str(document.get("path", ""))
            if path_scope and not path.startswith(path_scope):
                continue
            objects.append(
                {
                    "id": document.get("id"),
                    "type": document.get("type"),
                    "path": path,
                    "note_title": document.get("note_title"),
                    "paper_title": document.get("paper_title"),
                    "wikilink": document.get("wikilink"),
                }
            )
        return {"ok": True, "result": {"objects": objects[:limit]}}

    def list_tags(
        self,
        object_type: Annotated[
            Literal["note", "paper-card"] | None,
            Field(description="Optional type filter. Omit to include tags from both object types."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(
                description=(
                    "Optional path prefix filter such as notes/inbox or library/papers; "
                    "limits tags to documents under that path."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=200, description="Maximum number of distinct tag strings to return."),
        ] = 200,
    ) -> dict[str, object]:
        documents = self.cloud_store.account_documents(self.account_email)
        tags: set[str] = set()
        for document in documents:
            if object_type and document.get("type") != object_type:
                continue
            path = str(document.get("path", ""))
            if path_scope and not path.startswith(path_scope):
                continue
            frontmatter = document.get("frontmatter", {}) or {}
            for tag in frontmatter.get("tags", []):
                if isinstance(tag, str) and tag.strip():
                    tags.add(tag)
        return {"ok": True, "result": {"tags": sorted(tags)[:limit]}}


def build_cloud_mcp_server(
    *,
    store_path,
    account_email: str,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> FastMCP:
    cloud_store = CloudStore(store_path)
    tools = CloudMCPTools(cloud_store=cloud_store, account_email=account_email)
    server = FastMCP(
        "ShardMind Cloud",
        instructions=(
            SERVER_INSTRUCTIONS
            + " This hosted MCP server exposes the cloud-synced subset for one account and is "
            "currently read-only."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
    server.tool(name="search")(tools.search)
    _apply_strict_arg_model_config(server, "search")
    server.tool(name="fetch")(tools.fetch)
    _apply_strict_arg_model_config(server, "fetch")
    server.tool(name="shardmind_list_objects")(tools.list_objects)
    _apply_strict_arg_model_config(server, "shardmind_list_objects")
    server.tool(name="shardmind_list_tags")(tools.list_tags)
    _apply_strict_arg_model_config(server, "shardmind_list_tags")
    return server


def run_cloud_mcp_server(
    *,
    store_path,
    account_email: str,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> int:
    server = build_cloud_mcp_server(
        store_path=store_path,
        account_email=account_email,
        host=host,
        port=port,
    )
    try:
        server.run(transport="streamable-http")
        return 0
    except ShardMindError as exc:  # pragma: no cover
        raise RuntimeError(str(exc)) from exc
