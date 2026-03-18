# ShardMind

ShardMind is an MCP-first local research memory system.

By default, first startup creates and uses a generic Obsidian-style vault at
`~/Documents/ShardMind` if `SHARDMIND_VAULT_PATH` is not already set. That vault is treated like
any other vault: ShardMind only creates and manages its own folders inside it, and does not assume
exclusive ownership of the rest of the vault.

Useful commands:

```bash
UV_CACHE_DIR=.uv-cache uv run shardmind init-vault
UV_CACHE_DIR=.uv-cache uv run shardmind-mcp
```
