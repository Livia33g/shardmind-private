# Railway Cloud MCP Deploy

This is the fastest path to a public HTTPS MCP URL for ChatGPT testing.

## Environment

Set these variables in Railway:

- `PORT=8080`
- Either `SHARDMIND_CLOUD_ACCOUNT_EMAIL=your-email@example.com`
- Or `SHARDMIND_CLOUD_LINK_TOKEN=<issued-link-token>`
- `SHARDMIND_CLOUD_STORE_PATH=/data/cloud-store.json`
- `SHARDMIND_VAULT_PATH=/data/vault`
- `SHARDMIND_SQLITE_PATH=/data/shardmind.sqlite3`

## Build

Use the repo root with:

```bash
docker build -f Dockerfile.cloud-mcp -t shardmind-cloud-mcp .
```

For Railway, point the service at `Dockerfile.cloud-mcp`.

## Start

The container starts this automatically:

```bash
shardmind serve-cloud-mcp --host 0.0.0.0 --port $PORT --store-path $SHARDMIND_CLOUD_STORE_PATH --account-email $SHARDMIND_CLOUD_ACCOUNT_EMAIL --link-token $SHARDMIND_CLOUD_LINK_TOKEN
```

## Important

- Attach a persistent volume so `/data/cloud-store.json` survives restarts.
- This remote MCP server is account-scoped and currently read-only.
- The link-token path is the better MVP account-linking story for ChatGPT/Gemini, because it
  decouples the remote connector from the chat provider's login email.
- Before deploying, upload a sync bundle from ShardMind Desktop so the hosted cloud store has data.
- Once deployed, your ChatGPT MCP URL will be:

```text
https://your-service.up.railway.app/mcp
```
