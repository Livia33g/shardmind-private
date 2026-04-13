# ShardMind Desktop

Tauri-based companion app for making ShardMind feel install-once and background-ready.

Current scope:
- save and load core local settings
- start and stop the ShardMind MCP engine
- show basic service state in a desktop UI

Planned next:
- launch at login
- menu bar / system tray mode
- client detection and one-click setup for Claude, Codex, and Gemini CLI
- richer health checks, reindex actions, and log streaming

## Local Development

Prerequisites:
- Node.js 20+
- Rust toolchain
- system WebView requirements for Tauri on your platform

Install frontend dependencies:

```bash
cd desktop
npm install
```

Run the desktop app in development:

```bash
npm run tauri dev
```

Build a distributable app:

```bash
npm run tauri build
```

The app currently launches ShardMind with:

```bash
uv --directory /path/to/shardmind-code run --frozen shardmind-mcp
```

using the configured `SHARDMIND_VAULT_PATH` and `SHARDMIND_SQLITE_PATH`.
