"""CLI helpers for bootstrap and local tool invocation."""

from __future__ import annotations

import argparse
import json
import sys

from shardmind.bootstrap import build_runtime
from shardmind.vault.bootstrap import bootstrap_vault


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shardmind")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-vault", help="Create the canonical ShardMind vault layout.")

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a tool with a JSON payload.")
    invoke_parser.add_argument("tool_name")
    invoke_parser.add_argument("payload", help="JSON payload for the tool.")

    args = parser.parse_args(argv)
    runtime = build_runtime()

    if args.command == "init-vault":
        bootstrap_vault(runtime.settings.vault_path)
        print(runtime.settings.vault_path)
        return 0

    if args.command == "invoke":
        payload = json.loads(args.payload)
        response = runtime.tools.invoke(args.tool_name, payload)
        print(json.dumps(response, indent=2, sort_keys=True))
        return 0 if response.get("ok") else 1

    parser.print_help(sys.stderr)
    return 1
