"""CLI helpers for bootstrap and local tool invocation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from shardmind.bootstrap import build_runtime
from shardmind.cloud.mcp import run_cloud_mcp_server
from shardmind.cloud.main import run_cloud_server
from shardmind.mcp.main import run_http_server, run_server
from shardmind.vault.bootstrap import bootstrap_vault


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shardmind")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-vault", help="Create the canonical ShardMind vault layout.")
    subparsers.add_parser("reindex-all", help="Rebuild the derived SQLite index from the vault.")

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a tool with a JSON payload.")
    invoke_parser.add_argument("tool_name")
    invoke_parser.add_argument("payload", help="JSON payload for the tool.")
    export_cloud_parser = subparsers.add_parser(
        "export-cloud-bundle",
        help="Export a cloud-sync bundle from the local vault.",
    )
    export_cloud_parser.add_argument(
        "--selection",
        default="",
        help="Comma-separated path prefixes to include in the bundle.",
    )
    subparsers.add_parser("serve-mcp", help="Run the MCP stdio server.")
    serve_http_parser = subparsers.add_parser(
        "serve-http",
        help="Run the MCP Streamable HTTP server.",
    )
    serve_http_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the HTTP MCP server.",
    )
    serve_http_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the HTTP MCP server.",
    )
    serve_cloud_parser = subparsers.add_parser(
        "serve-cloud",
        help="Run the hosted bridge contract for cloud-connected clients.",
    )
    serve_cloud_parser.add_argument("--host", default="127.0.0.1")
    serve_cloud_parser.add_argument("--port", type=int, default=8787)
    serve_cloud_parser.add_argument(
        "--store-path",
        default=os.environ.get("SHARDMIND_CLOUD_STORE_PATH"),
        help="Optional JSON store path for uploaded cloud-sync bundles.",
    )
    serve_cloud_parser.add_argument(
        "--bearer-token",
        default=os.environ.get("SHARDMIND_CLOUD_BEARER_TOKEN"),
        help="Optional bearer token required for hosted bridge requests.",
    )
    serve_cloud_mcp_parser = subparsers.add_parser(
        "serve-cloud-mcp",
        help="Run a remote MCP server backed by the hosted cloud store.",
    )
    serve_cloud_mcp_parser.add_argument("--host", default="127.0.0.1")
    serve_cloud_mcp_parser.add_argument("--port", type=int, default=8080)
    serve_cloud_mcp_parser.add_argument(
        "--store-path",
        default=os.environ.get("SHARDMIND_CLOUD_STORE_PATH"),
        help="Optional JSON store path for uploaded cloud-sync bundles.",
    )
    serve_cloud_mcp_parser.add_argument(
        "--account-email",
        default=os.environ.get("SHARDMIND_CLOUD_ACCOUNT_EMAIL"),
        help="Account email whose synced documents should be exposed over remote MCP.",
    )
    serve_cloud_mcp_parser.add_argument(
        "--link-token",
        default=os.environ.get("SHARDMIND_CLOUD_LINK_TOKEN"),
        help="Optional issued ShardMind cloud link token that resolves to the synced account.",
    )
    serve_cloud_mcp_parser.add_argument(
        "--bearer-token",
        default=os.environ.get("SHARDMIND_CLOUD_BEARER_TOKEN"),
        help="Optional bearer token required for sync/session bridge routes on the hosted service.",
    )

    args = parser.parse_args(argv)
    runtime = build_runtime()
    try:
        if args.command == "init-vault":
            bootstrap_vault(runtime.settings.vault_path)
            print(runtime.settings.vault_path)
            return 0

        if args.command == "reindex-all":
            records, skipped_paths = runtime.vault.list_indexable_objects()
            runtime.index.rebuild(records)
            print(len(records))
            if skipped_paths:
                print(
                    f"Skipped {len(skipped_paths)} malformed file(s): {', '.join(skipped_paths)}",
                    file=sys.stderr,
                )
            return 0

        if args.command == "invoke":
            payload = json.loads(args.payload)
            response = runtime.tools.invoke(args.tool_name, payload)
            print(json.dumps(response, indent=2, sort_keys=True))
            return 0 if response.get("ok") else 1

        if args.command == "export-cloud-bundle":
            selection = [item.strip() for item in args.selection.split(",") if item.strip()]
            records, _ = runtime.vault.list_indexable_objects()
            documents = [
                record.to_document(path)
                for record, path in records
                if not selection or any(path.startswith(prefix) for prefix in selection)
            ]
            print(
                json.dumps(
                    {
                        "manifest": {
                            "local_source_of_truth": "local-shardmind-vault",
                            "vault_path": str(runtime.settings.vault_path),
                            "selection": selection,
                        },
                        "documents": documents,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "serve-mcp":
            return run_server(runtime.tools)

        if args.command == "serve-http":
            return run_http_server(runtime.tools, host=args.host, port=args.port)

        if args.command == "serve-cloud":
            return run_cloud_server(
                runtime,
                host=args.host,
                port=args.port,
                store_path=Path(args.store_path) if args.store_path else None,
                bearer_token=args.bearer_token,
            )

        if args.command == "serve-cloud-mcp":
            if not args.account_email and not args.link_token:
                raise SystemExit(
                    "--account-email/SHARDMIND_CLOUD_ACCOUNT_EMAIL or "
                    "--link-token/SHARDMIND_CLOUD_LINK_TOKEN is required."
                )
            store_path = (
                Path(args.store_path)
                if args.store_path
                else runtime.settings.sqlite_path.parent / "cloud-store.json"
            )
            return run_cloud_mcp_server(
                store_path=store_path,
                account_email=args.account_email,
                link_token=args.link_token,
                bearer_token=args.bearer_token,
                host=args.host,
                port=args.port,
            )

        parser.print_help(sys.stderr)
        return 1
    finally:
        runtime.close()
