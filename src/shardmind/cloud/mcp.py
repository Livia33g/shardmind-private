"""Cloud-backed MCP server for remote ChatGPT/Gemini connector use."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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
    account_email: str | None = None,
    link_token: str | None = None,
    bearer_token: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> FastMCP:
    cloud_store = CloudStore(store_path)
    resolved_account_email = ""
    if link_token:
        resolved_account_email = cloud_store.account_from_link_token(link_token) or ""
        if not resolved_account_email:
            raise InvalidInputError("Unknown or unlinked ShardMind cloud link token.")
    elif account_email:
        resolved_account_email = account_email.strip().lower()
    else:
        raise InvalidInputError("Either account_email or link_token is required.")

    tools = CloudMCPTools(cloud_store=cloud_store, account_email=resolved_account_email)
    server = FastMCP(
        "ShardMind Cloud",
        instructions=(
            SERVER_INSTRUCTIONS
            + " This hosted MCP server exposes the cloud-synced subset for one account and is "
            "currently read-only. It is linked to one ShardMind account via either a configured "
            "account email or an issued ShardMind link token."
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

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health_route(request: Request) -> Response:
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        return JSONResponse(
            {
                "ok": True,
                "service": "shardmind-cloud",
                "version": "0.2",
                "routes": [
                    "/health",
                    "/v1/account/session",
                    "/v1/account/link-token",
                    "/v1/search",
                    "/v1/fetch",
                    "/v1/sync/bundle",
                    "/mcp",
                ],
                "has_synced_documents": cloud_store.has_documents(),
                "synced_accounts": cloud_store.account_count(),
                "mcp_account_email": resolved_account_email,
                "authenticated_as": auth.get("account_email") or auth["kind"],
            }
        )

    @server.custom_route("/v1/account/session", methods=["POST"], include_in_schema=False)
    async def account_session_route(request: Request) -> Response:
        payload = await _read_request_json(request)
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        request_email = str(payload.get("account_email", "")).strip().lower()
        if not request_email:
            return _error_response("INVALID_INPUT", "account_email is required.", status=400)
        if auth["kind"] == "session" and auth.get("account_email") != request_email:
            return _error_response(
                "FORBIDDEN",
                "Session tokens may only refresh their own account session.",
                status=403,
            )
        session = cloud_store.issue_session(request_email)
        return JSONResponse({"ok": True, "result": session})

    @server.custom_route("/v1/account/link-token", methods=["POST"], include_in_schema=False)
    async def account_link_route(request: Request) -> Response:
        payload = await _read_request_json(request)
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        request_email = str(payload.get("account_email", "")).strip().lower()
        if not request_email:
            return _error_response("INVALID_INPUT", "account_email is required.", status=400)
        if auth["kind"] == "session" and auth.get("account_email") != request_email:
            return _error_response(
                "FORBIDDEN",
                "Session tokens may only issue link tokens for their own account.",
                status=403,
            )
        link = cloud_store.issue_link_token(request_email, label=str(payload.get("label", "")))
        return JSONResponse({"ok": True, "result": link})

    @server.custom_route("/v1/search", methods=["POST"], include_in_schema=False)
    async def search_route(request: Request) -> Response:
        payload = await _read_request_json(request)
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        response = cloud_store.search(
            account_email=_resolve_account_email(payload, auth),
            query=str(payload.get("query", "")),
            object_types=payload.get("object_types"),
            path_scope=payload.get("path_scope"),
            top_k=int(payload.get("top_k", 10)),
            tags=payload.get("tags"),
        )
        return JSONResponse(response, status_code=200 if response.get("ok") else 400)

    @server.custom_route("/v1/fetch", methods=["POST"], include_in_schema=False)
    async def fetch_route(request: Request) -> Response:
        payload = await _read_request_json(request)
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        response = cloud_store.fetch(
            account_email=_resolve_account_email(payload, auth),
            document_id=str(payload.get("id", "")),
        )
        return JSONResponse(response, status_code=200 if response.get("ok") else 400)

    @server.custom_route("/v1/sync/bundle", methods=["POST"], include_in_schema=False)
    async def sync_bundle_route(request: Request) -> Response:
        payload = await _read_request_json(request)
        auth = _authorize_request(request, cloud_store, bearer_token)
        if auth is None:
            return _unauthorized_response()
        manifest = payload.get("manifest")
        documents = payload.get("documents")
        if not isinstance(manifest, dict) or not isinstance(documents, list):
            return _error_response(
                "INVALID_INPUT",
                "Bundle must include manifest object and documents array.",
                status=400,
            )
        manifest_account_email = str(manifest.get("account_email", "")).strip().lower()
        if not manifest_account_email:
            return _error_response("INVALID_INPUT", "manifest.account_email is required.", status=400)
        if auth["kind"] == "session" and auth.get("account_email") != manifest_account_email:
            return _error_response(
                "FORBIDDEN",
                "Session tokens may only upload for their own account.",
                status=403,
            )
        cloud_store.write_bundle(
            manifest,
            [document for document in documents if isinstance(document, dict)],
        )
        return JSONResponse(
            {
                "ok": True,
                "result": {
                    "stored_documents": len(documents),
                    "account_email": manifest_account_email,
                    "sync_scope": manifest.get("sync_scope", ""),
                },
            }
        )

    return server


def run_cloud_mcp_server(
    *,
    store_path,
    account_email: str | None = None,
    link_token: str | None = None,
    bearer_token: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> int:
    server = build_cloud_mcp_server(
        store_path=store_path,
        account_email=account_email,
        link_token=link_token,
        bearer_token=bearer_token,
        host=host,
        port=port,
    )
    try:
        server.run(transport="streamable-http")
        return 0
    except ShardMindError as exc:  # pragma: no cover
        raise RuntimeError(str(exc)) from exc


async def _read_request_json(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise InvalidInputError("Request body must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise InvalidInputError("Request body must be a JSON object.")
    return payload


def _authorize_request(
    request: Request,
    cloud_store: CloudStore,
    bearer_token: str | None,
) -> dict[str, str | None] | None:
    provided = request.headers.get("Authorization", "")
    token = provided.removeprefix("Bearer ").strip() if provided.startswith("Bearer ") else ""
    if bearer_token is None and not token:
        return {"kind": "anonymous", "account_email": None}
    if bearer_token is not None and token == bearer_token:
        return {"kind": "bridge", "account_email": None}
    session_account = cloud_store.account_from_session_token(token)
    if session_account is not None:
        return {"kind": "session", "account_email": session_account}
    return None


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Missing or invalid bearer token.",
            },
        },
        status_code=401,
    )


def _error_response(code: str, message: str, *, status: int) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
    )


def _resolve_account_email(
    payload: dict[str, object],
    auth: dict[str, str | None],
) -> str | None:
    payload_email = str(payload.get("account_email", "")).strip().lower()
    if payload_email:
        return payload_email
    return auth.get("account_email")
