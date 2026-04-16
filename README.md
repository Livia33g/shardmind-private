# ShardMind

ShardMind is an MCP-first local research memory system. It is compatible with [Obsidian](https://obsidian.md), but is standalone.

Current state:
- notes and paper cards are stored as canonical Markdown in an Obsidian-style vault
- note and paper-card files can live in nested subfolders within their allowed roots
- the MCP server supports deterministic create/read/list/search flows for both object types
- paper-card editing is a structured patch operation driven by the MCP client
- ShardMind now uses local-first hybrid retrieval with chunk embeddings, resurfacing, and lightweight capture flows
- a Tauri desktop companion lives under `desktop/` for install-once background setup

## Install

Requirements:
- Python 3.10+
- `uv`

Install the project and contributor tooling:

```bash
uv sync --extra dev
```

Fastest local setup for a fresh machine:

```bash
uv sync --extra dev
uv run shardmind-mcp
```

For a private alpha tester who should not need the repo checkout after install:

```bash
pip install -e .
shardmind-mcp
```

If `shardmind-mcp` is installed on the machine and available on `PATH`, ShardMind Desktop can now
launch it directly without needing the repo path or `uv` fields.

If you are not using `uv`, install the package into your current Python environment:

```bash
pip install -e .
shardmind serve-mcp
```

Run the supported local checks before opening a PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
uv build
```

Contributor workflow details live in `CONTRIBUTING.md`.

## Run

By default, ShardMind uses `~/Documents/ShardMind` as its vault if `SHARDMIND_VAULT_PATH` is not
set. On first startup, it creates the required folder structure inside that vault.

Useful commands:

```bash
uv run shardmind init-vault
uv run shardmind reindex-all
uv run shardmind-mcp
uv run shardmind serve-http --host 127.0.0.1 --port 8000
uv run shardmind serve-cloud --host 127.0.0.1 --port 8787
uv run shardmind serve-cloud-mcp --host 127.0.0.1 --port 8080 --account-email "livia@example.com"
uv run shardmind serve-cloud-mcp --host 127.0.0.1 --port 8080 --link-token "<issued-link-token>"
uv run shardmind export-cloud-bundle --selection "notes/projects,library/papers/ml"
```

You can also override paths explicitly:

```bash
export SHARDMIND_VAULT_PATH="$HOME/Documents/ShardMind"
export SHARDMIND_SQLITE_PATH="$HOME/Library/Application Support/shardmind/shardmind.sqlite3"
uv run shardmind-mcp
```

For remote-MCP clients that need HTTP instead of stdio:

```bash
export SHARDMIND_VAULT_PATH="$HOME/Documents/ShardMind"
export SHARDMIND_SQLITE_PATH="$HOME/Library/Application Support/shardmind/shardmind.sqlite3"
uv run shardmind serve-http --host 127.0.0.1 --port 8000
```

Quick start for another developer pulling this repo fresh:

```bash
git clone <repo-url>
cd shardmind
uv sync --extra dev
export SHARDMIND_VAULT_PATH="$HOME/Documents/ShardMind"
export SHARDMIND_SQLITE_PATH="$HOME/Library/Application Support/shardmind/shardmind.sqlite3"
uv run shardmind serve-http --host 127.0.0.1 --port 8000
```

If your team is using plain `pip` instead of `uv`:

```bash
git clone <repo-url>
cd shardmind
pip install -e .
export SHARDMIND_VAULT_PATH="$HOME/Documents/ShardMind"
export SHARDMIND_SQLITE_PATH="$HOME/Library/Application Support/shardmind/shardmind.sqlite3"
shardmind serve-http --host 127.0.0.1 --port 8000
```

## Claude Desktop MCP Setup

Claude Desktop can launch ShardMind for you as a local MCP server over stdio. You do not need to
start it manually in a separate terminal during normal use.

Note: MCPB-style support for the newer in-app path should be added later. For the moment, use the
current config-edit route in Claude Desktop:

1. Open `Claude Desktop`.
2. Go to `Settings > Developer`.
3. Click `Edit Config`.
4. Add the `ShardMind` MCP server entry below to the config JSON.

```json
{
  "mcpServers": {
    "ShardMind": {
      "type": "stdio",
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "--directory",
        "/absolute/path/to/shardmind",
        "run",
        "--frozen",
        "shardmind-mcp"
      ],
      "env": {
        "SHARDMIND_VAULT_PATH": "/Users/yourname/Documents/ShardMind",
        "SHARDMIND_SQLITE_PATH": "/Users/yourname/Library/Application Support/shardmind/shardmind.sqlite3"
      }
    }
  }
}
```

If your config already contains other top-level keys such as `preferences`, keep them and merge in
the `mcpServers.ShardMind` block.

After saving the config:

1. Quit Claude Desktop completely.
2. Reopen Claude Desktop.
3. Start a new chat.
4. Try prompts like:
   - `Use ShardMind to create a note titled "test note" with content "hello from Claude".`
   - `Use ShardMind to create a note with relative_path "archive/2026/test-note.md" and content "hello from Claude".`
   - `Use ShardMind to create a paper card titled "test paper" with sections.notes set to "example abstract".`
   - `Use ShardMind to create a paper card with relative_path "library/papers/ml/test-paper.md" and sections.notes set to "example abstract".`
   - `Use ShardMind to search for "hello".`

Current exported MCP tools:
- `shardmind_create_note`
- `shardmind_append_to_note`
- `shardmind_edit_note`
- `shardmind_create_paper_card`
- `shardmind_edit_paper_card`
- `shardmind_get_object`
- `shardmind_move_object`
- `shardmind_delete_object`
- `shardmind_reindex_all`
- `shardmind_list_objects`
- `shardmind_list_tags`
- `shardmind_search`
- `search` (alias for clients that expect a generic search tool)
- `fetch` (alias for `shardmind_get_object`)

## Codex MCP Setup

Codex can connect to the same local ShardMind MCP server. Add a server entry that points at the
repo and starts the stdio transport:

```toml
[mcp_servers.shardmind]
command = "/absolute/path/to/uv"
args = [
  "--directory",
  "/absolute/path/to/shardmind",
  "run",
  "--frozen",
  "shardmind-mcp",
]

[mcp_servers.shardmind.env]
SHARDMIND_VAULT_PATH = "/Users/yourname/Documents/ShardMind"
SHARDMIND_SQLITE_PATH = "/Users/yourname/Library/Application Support/shardmind/shardmind.sqlite3"
```

If your Codex client expects an HTTP MCP server instead, run:

```bash
uv run shardmind serve-http --host 127.0.0.1 --port 8000
```

and point the client at:

```text
http://127.0.0.1:8000/mcp
```

## ChatGPT Remote MCP Setup

For OpenAI clients that use remote MCP over HTTP, run ShardMind with the Streamable HTTP server:

```bash
export SHARDMIND_VAULT_PATH="$HOME/Documents/ShardMind"
export SHARDMIND_SQLITE_PATH="$HOME/Library/Application Support/shardmind/shardmind.sqlite3"
uv run shardmind serve-http --host 127.0.0.1 --port 8000
```

Then register the server URL:

```text
http://127.0.0.1:8000/mcp
```

The generic `search` and `fetch` aliases are exported specifically to help MCP clients that look
for those conventional tool names, while the full `shardmind_*` tool surface remains available.

## Cloud Bridge Contract

ShardMind also includes an early hosted-bridge contract for future cloud-connected access:

```bash
export SHARDMIND_CLOUD_BEARER_TOKEN="replace-me"
uv run shardmind serve-cloud --host 127.0.0.1 --port 8787 --bearer-token "$SHARDMIND_CLOUD_BEARER_TOKEN"
```

Routes:
- `GET /health`
- `POST /v1/account/session`
- `POST /v1/search`
- `POST /v1/fetch`
- `POST /v1/sync/bundle`

The hosted bridge now stores synced bundles per account email. For hosted `search` and `fetch`
requests, include `account_email` whenever more than one account has been synced into the same
bridge store. The new account-session route can mint a per-user session token so desktop clients do
not need to keep using the bridge bootstrap token for every request.

Example account-session request:

```bash
curl -X POST http://127.0.0.1:8787/v1/account/session \
  -H "Authorization: Bearer $SHARDMIND_CLOUD_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"account_email":"livia@example.com"}'
```

Example search request:

```bash
curl -X POST http://127.0.0.1:8787/v1/search \
  -H "Authorization: Bearer $SHARDMIND_CLOUD_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"account_email":"livia@example.com","query":"memory systems","top_k":5}'
```

Example fetch request:

```bash
curl -X POST http://127.0.0.1:8787/v1/fetch \
  -H "Authorization: Bearer $SHARDMIND_CLOUD_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"account_email":"livia@example.com","id":"note-..."}'
```

Example sync bundle upload:

```bash
curl -X POST http://127.0.0.1:8787/v1/sync/bundle \
  -H "Authorization: Bearer $SHARDMIND_CLOUD_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d @cloud-sync-bundle.json
```

The uploaded bundle's `manifest.account_email` field is required so the bridge can keep user data
isolated.

## Remote MCP For ChatGPT / Gemini Chat

ShardMind now also includes a cloud-backed remote MCP server. This is the server type ChatGPT and
Gemini chat can use once it is deployed to a public HTTPS URL.

Run it locally against the hosted sync store for one account:

```bash
export SHARDMIND_CLOUD_ACCOUNT_EMAIL="livia@example.com"
uv run shardmind serve-cloud-mcp --host 127.0.0.1 --port 8080 --account-email "$SHARDMIND_CLOUD_ACCOUNT_EMAIL"
```

Or, for a real account-linking flow that does not depend on ChatGPT's login email matching the
synced ShardMind account, run it with an issued link token:

```bash
export SHARDMIND_CLOUD_LINK_TOKEN="<issued-link-token>"
uv run shardmind serve-cloud-mcp --host 127.0.0.1 --port 8080 --link-token "$SHARDMIND_CLOUD_LINK_TOKEN"
```

The MCP endpoint will be:

```text
http://127.0.0.1:8080/mcp
```

This remote MCP server is currently:
- backed by the uploaded cloud-sync store rather than the local vault
- scoped to one synced account email or one issued ShardMind link token
- read-only, exposing `search`, `fetch`, `shardmind_list_objects`, and `shardmind_list_tags`

To issue a link token from the hosted bridge, first create an account session through
`/v1/account/session`, then request `/v1/account/link-token` for that same ShardMind account. This
lets a remote MCP connector bind to a ShardMind account explicitly instead of assuming the chat
provider's login email matches your ShardMind sync account.

To connect this to ChatGPT properly, the remaining operational step is to deploy
`serve-cloud-mcp` on a public HTTPS URL and register that URL as a custom remote MCP connector in
ChatGPT developer mode or business/enterprise connector settings.

For the fastest hosted path, see [deploy/railway-cloud-mcp.md](/Users/liviaguttieres/Documents/shardmind-code/deploy/railway-cloud-mcp.md). The target end state is a public MCP URL like:

```text
https://your-service.example.com/mcp
```

## Suggested Prompts

Once Claude Desktop is connected to the `ShardMind` MCP server, prompts like these should work
well:


- `Summarize this conversation and save it as a note in ShardMind titled "memory architecture recap".`
- `Find [relevant paper] online and save a paper card for it in ShardMind.`
- `Search ShardMind for my notes and paper cards about memory systems.`

## Notes

- `desktop/` is the beginning of the cross-platform ShardMind companion app. It is intended to
  make local install, background launch, and client integration simpler for end users.
- `dev-docs/` is scratch/reference material and not part of the runtime product surface.
- The vault is canonical; the SQLite index is derived and can be rebuilt.
- `system/**` is non-indexable and reserved for ShardMind internals.
- `assets/**` is attachment storage, not note or paper-card storage.
- `library/papers/**` is reserved for paper cards and their subfolders.
- Notes may be created under `notes/**`, `archive/**`, or `library/**` except `library/papers/**`.
- `shardmind_create_note` and `shardmind_create_paper_card` accept optional `relative_path`
  parameters for explicit nested placement; create/edit flows remain ID-based after creation.
- `shardmind_move_object` moves an existing object by id to a new allowed `relative_path` without
  changing its id.
- `shardmind_delete_object` deletes an existing object by id and removes it from the derived index.
- `shardmind_reindex_all` manually rebuilds the derived SQLite index from the vault and reports any
  skipped malformed paths. Calls `uv run shardmind reindex-all`, which is the supported repair path after manual vault edits or index drift.
- `shardmind_get_object`, `shardmind_list_objects`, and `shardmind_search` return `note_title` or
  `paper_title` plus a `wikilink` file stem so MCP clients can create correct Obsidian links
  without confusing frontmatter title with link target.
