"""Minimal hosted bridge contract for Cloud-Connected Mode."""

from __future__ import annotations

import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from shardmind.bootstrap import Runtime, build_runtime
from shardmind.mcp.tools import KnowledgeTools


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: dict[str, Any],
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


class CloudStore:
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {"accounts": {}}
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        if "accounts" in payload:
            return payload
        # Migrate the original single-bundle format in place.
        manifest = payload.get("manifest") or {}
        account_email = str(manifest.get("account_email", "")).strip().lower()
        accounts: dict[str, Any] = {}
        if account_email:
            accounts[account_email] = {
                "manifest": manifest,
                "documents": payload.get("documents", []),
                "session": None,
            }
        migrated = {"accounts": accounts}
        self.store_path.write_text(json.dumps(migrated, indent=2), encoding="utf-8")
        return migrated

    def write_bundle(self, manifest: dict[str, Any], documents: list[dict[str, Any]]) -> None:
        account_email = str(manifest.get("account_email", "")).strip().lower()
        if not account_email:
            raise ValueError("manifest.account_email is required")
        payload = self.read()
        payload.setdefault("accounts", {})
        payload["accounts"].setdefault(account_email, {})
        payload["accounts"][account_email] = {
            **payload["accounts"][account_email],
            "manifest": manifest,
            "documents": documents,
        }
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def issue_session(self, account_email: str) -> dict[str, Any]:
        normalized_email = account_email.strip().lower()
        if not normalized_email:
            raise ValueError("account_email is required")
        payload = self.read()
        payload.setdefault("accounts", {})
        account = payload["accounts"].setdefault(normalized_email, {})
        token = secrets.token_urlsafe(24)
        session = {
            "token": token,
        }
        account["session"] = session
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "account_email": normalized_email,
            "session_token": token,
        }

    def account_from_session_token(self, token: str | None) -> str | None:
        if not token:
            return None
        payload = self.read()
        for account_email, account in payload.get("accounts", {}).items():
            session = account.get("session") or {}
            if session.get("token") == token:
                return account_email
        return None

    def account_documents(self, account_email: str | None) -> list[dict[str, Any]]:
        payload = self.read()
        accounts = payload.get("accounts", {})
        if not accounts:
            return []
        normalized_email = str(account_email or "").strip().lower()
        if normalized_email:
            return list(accounts.get(normalized_email, {}).get("documents", []))
        if len(accounts) == 1:
            return list(next(iter(accounts.values())).get("documents", []))
        return []

    def search(
        self,
        *,
        account_email: str | None,
        query: str,
        object_types: list[str] | None,
        path_scope: str | None,
        top_k: int,
        tags: list[str] | None,
    ) -> dict[str, Any]:
        normalized = query.strip().lower()
        if not normalized:
            return {
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "query must be a non-empty string."},
            }
        matches: list[dict[str, Any]] = []
        documents = self.account_documents(account_email)
        if not documents:
            return {
                "ok": False,
                "error": {
                    "code": "ACCOUNT_NOT_SYNCED",
                    "message": "No synced documents found for this account.",
                },
            }
        for document in documents:
            doc_type = str(document.get("type", ""))
            path = str(document.get("path", ""))
            doc_tags = list(document.get("frontmatter", {}).get("tags", []))
            if object_types and doc_type not in object_types:
                continue
            if path_scope and not path.startswith(path_scope):
                continue
            if tags and not set(tags).issubset(set(doc_tags)):
                continue
            haystacks = [path, json.dumps(document.get("sections", {})), json.dumps(document.get("frontmatter", {}))]
            if normalized not in " ".join(haystacks).lower():
                continue
            title = str(document.get("note_title") or document.get("paper_title") or "")
            matches.append(
                {
                    "id": document.get("id"),
                    "type": doc_type,
                    "path": path,
                    "score": 1.0,
                    "matched_sections": list(document.get("sections", {}).keys())[:3],
                    "snippet": title or path,
                    "tags": doc_tags,
                    "note_title": document.get("note_title"),
                    "paper_title": document.get("paper_title"),
                    "wikilink": document.get("wikilink"),
                }
            )
        return {"ok": True, "result": {"query": query, "results": matches[:top_k], "top_k": top_k}}

    def fetch(self, *, account_email: str | None, document_id: str) -> dict[str, Any]:
        documents = self.account_documents(account_email)
        if not documents:
            return {
                "ok": False,
                "error": {
                    "code": "ACCOUNT_NOT_SYNCED",
                    "message": "No synced documents found for this account.",
                },
            }
        for document in documents:
            if str(document.get("id")) == document_id:
                return {"ok": True, "result": document}
        return {
            "ok": False,
            "error": {"code": "OBJECT_NOT_FOUND", "message": f"Unknown object '{document_id}'."},
        }

    def has_documents(self) -> bool:
        return bool(self.read().get("accounts", {}))

    def account_count(self) -> int:
        return len(self.read().get("accounts", {}))


def _make_handler(
    tools: KnowledgeTools,
    cloud_store: CloudStore,
    bearer_token: str | None,
) -> type[BaseHTTPRequestHandler]:
    class CloudBridgeHandler(BaseHTTPRequestHandler):
        server_version = "ShardMindCloud/0.1"

        def do_GET(self) -> None:  # noqa: N802
            auth = self._authorize()
            if auth is None:
                return
            if self.path == "/health":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "service": "shardmind-cloud",
                        "version": "0.1",
                        "routes": ["/health", "/v1/account/session", "/v1/search", "/v1/fetch", "/v1/sync/bundle"],
                        "has_synced_documents": cloud_store.has_documents(),
                        "synced_accounts": cloud_store.account_count(),
                        "authenticated_as": auth.get("account_email") or auth["kind"],
                    },
                )
                return
            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown route."}},
            )

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = _read_json_body(self)
            except json.JSONDecodeError:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": {
                            "code": "INVALID_JSON",
                            "message": "Request body must be valid JSON.",
                        },
                    },
                )
                return
            auth = self._authorize()
            if auth is None:
                return

            account_email = _resolve_account_email(payload, auth)

            if self.path == "/v1/account/session":
                request_email = str(payload.get("account_email", "")).strip().lower()
                if not request_email:
                    _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {
                            "ok": False,
                            "error": {
                                "code": "INVALID_INPUT",
                                "message": "account_email is required.",
                            },
                        },
                    )
                    return
                if auth["kind"] == "session" and auth.get("account_email") != request_email:
                    _json_response(
                        self,
                        HTTPStatus.FORBIDDEN,
                        {
                            "ok": False,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": "Session tokens may only refresh their own account session.",
                            },
                        },
                    )
                    return
                session = cloud_store.issue_session(request_email)
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {"ok": True, "result": session},
                )
                return

            if self.path == "/v1/search":
                if cloud_store.has_documents():
                    response = cloud_store.search(
                        account_email=account_email,
                        query=str(payload.get("query", "")),
                        object_types=payload.get("object_types"),
                        path_scope=payload.get("path_scope"),
                        top_k=int(payload.get("top_k", 10)),
                        tags=payload.get("tags"),
                    )
                else:
                    response = tools.search(
                        query=str(payload.get("query", "")),
                        object_types=payload.get("object_types"),
                        path_scope=payload.get("path_scope"),
                        top_k=int(payload.get("top_k", 10)),
                        tags=payload.get("tags"),
                    )
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
                _json_response(self, status, response)
                return

            if self.path == "/v1/fetch":
                if cloud_store.has_documents():
                    response = cloud_store.fetch(
                        account_email=account_email,
                        document_id=str(payload.get("id", "")),
                    )
                else:
                    response = tools.get_object(id=str(payload.get("id", "")))
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
                _json_response(self, status, response)
                return

            if self.path == "/v1/sync/bundle":
                manifest = payload.get("manifest")
                documents = payload.get("documents")
                if not isinstance(manifest, dict) or not isinstance(documents, list):
                    _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {
                            "ok": False,
                            "error": {
                                "code": "INVALID_INPUT",
                                "message": "Bundle must include manifest object and documents array.",
                            },
                        },
                    )
                    return
                account_email = str(manifest.get("account_email", "")).strip()
                if not account_email:
                    _json_response(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        {
                            "ok": False,
                            "error": {
                                "code": "INVALID_INPUT",
                                "message": "manifest.account_email is required.",
                            },
                        },
                    )
                    return
                if auth["kind"] == "session" and auth.get("account_email") != account_email:
                    _json_response(
                        self,
                        HTTPStatus.FORBIDDEN,
                        {
                            "ok": False,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": "Session tokens may only upload for their own account.",
                            },
                        },
                    )
                    return
                cloud_store.write_bundle(manifest, [doc for doc in documents if isinstance(doc, dict)])
                response = {
                    "ok": True,
                    "result": {
                        "stored_documents": len(documents),
                        "account_email": account_email,
                        "sync_scope": manifest.get("sync_scope", ""),
                    },
                }
                status = HTTPStatus.OK if response.get("ok") else HTTPStatus.BAD_REQUEST
                _json_response(self, status, response)
                return

            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"code": "NOT_FOUND", "message": "Unknown route."}},
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _authorize(self) -> dict[str, Any] | None:
            provided = self.headers.get("Authorization", "")
            token = provided.removeprefix("Bearer ").strip() if provided.startswith("Bearer ") else ""
            if bearer_token is None and not token:
                return {"kind": "anonymous", "account_email": None}
            if bearer_token is not None and token == bearer_token:
                return {"kind": "bridge", "account_email": None}
            session_account = cloud_store.account_from_session_token(token)
            if session_account is not None:
                return {"kind": "session", "account_email": session_account}
            _json_response(
                self,
                HTTPStatus.UNAUTHORIZED,
                {
                    "ok": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid bearer token.",
                    },
                },
            )
            return None

    return CloudBridgeHandler


def _resolve_account_email(payload: dict[str, Any], auth: dict[str, Any]) -> str | None:
    payload_email = str(payload.get("account_email", "")).strip().lower()
    if payload_email:
        return payload_email
    return auth.get("account_email")


def build_cloud_server(
    runtime: Runtime,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    store_path: Path | None = None,
    bearer_token: str | None = None,
) -> HTTPServer:
    server = HTTPServer(
        (host, port),
        _make_handler(runtime.tools, CloudStore(store_path or runtime.settings.sqlite_path.parent / "cloud-store.json"), bearer_token),
    )
    server.runtime = runtime  # type: ignore[attr-defined]
    return server


def run_cloud_server(
    runtime: Runtime,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    store_path: Path | None = None,
    bearer_token: str | None = None,
) -> int:
    server = build_cloud_server(
        runtime,
        host=host,
        port=port,
        store_path=store_path,
        bearer_token=bearer_token,
    )
    try:
        server.serve_forever()
        return 0
    finally:
        server.server_close()
        runtime.close()


def main() -> int:
    runtime = build_runtime()
    host = os.environ.get("SHARDMIND_CLOUD_HOST", "127.0.0.1")
    port = int(os.environ.get("SHARDMIND_CLOUD_PORT", "8787"))
    store_path = Path(
        os.environ.get(
            "SHARDMIND_CLOUD_STORE_PATH",
            runtime.settings.sqlite_path.parent / "cloud-store.json",
        )
    )
    bearer_token = os.environ.get("SHARDMIND_CLOUD_BEARER_TOKEN")
    return run_cloud_server(
        runtime,
        host=host,
        port=port,
        store_path=store_path,
        bearer_token=bearer_token,
    )
