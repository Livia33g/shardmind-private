# ShardMind Private Alpha Setup

This guide is for trusted technical alpha testers on macOS.

ShardMind currently works best with:
- Claude Desktop
- Cursor
- Codex
- Gemini CLI

ChatGPT support exists through hosted cloud mode, but it should be treated as optional for now.
Gemini chat is not first-class yet.

## What You Will Receive

You should receive:
- the ShardMind Desktop DMG

The desktop app can now install a managed ShardMind engine for you on first run.
You should only need the separate Python wheel if the in-app engine install fails.

## Requirements

- macOS
- Python 3.10+
- one supported AI client:
  - Claude Desktop
  - Cursor
  - Codex
  - Gemini CLI

## Install

### 1. Install ShardMind Desktop

Open the DMG and drag `ShardMind Desktop.app` into Applications.

### 2. Install the ShardMind engine

Open `ShardMind Desktop`, then use the `Install Engine` button in the Setup section.

If that succeeds, the app will install a managed local ShardMind engine automatically.

Only use the separate wheel if the in-app install fails and you are asked to fall back to manual setup.

## First Run

1. Open `ShardMind Desktop`
2. Set:
   - `Vault Path`
   - `SQLite Path`
3. Leave `Repo Path` and `uv Path` empty unless you are doing a developer-style fallback setup
4. Click `Start Service`

If the service starts, the app should show ShardMind as running.

## Connect Your AI Client

In `Assistant Integrations`, use the install button for one of:
- Claude Desktop
- Cursor
- Codex
- Gemini CLI

Then fully restart that client.

## Suggested First Tests

Try prompts like:

- `Use ShardMind to create a note titled "alpha test" with content "hello from alpha".`
- `Use ShardMind to search for "alpha test".`
- `ShardMind, take note of this idea.`
- `Use ShardMind to bring back up prior memories about this topic.`

## What Feedback We Care About

Please focus feedback on:
- setup friction
- whether you actually wanted to use it again after the first test
- whether note capture felt useful
- whether resurfaced memories felt relevant or noisy
- whether it helped save useful AI-derived insights from getting lost

## Known Alpha Reality

This is still a private technical alpha. Expect:
- some rough edges
- setup that is more technical than the final product
- local-first use to be much better than Gemini chat–style compatibility

If something breaks, please share:
- what client you were using
- what action you tried
- the exact error message
