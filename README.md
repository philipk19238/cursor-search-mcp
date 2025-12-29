# Cursor Search MCP

Expose Cursor's semantic code search through MCP.

## Requirements

- Python 3.10+
- Cursor installed and logged in (once)
- uv or pip

Cursor must index the repo. Open it in Cursor and wait for indexing to finish.

## Install

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Run

```bash
cursor-search-mcp
# or
fastmcp run src/cursor_search_mcp/server.py
```

## MCP Client Setup

### Claude Code

```bash
claude mcp add cursor-search -- cursor-search-mcp
```

Or add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "cursor-search": {
      "command": "cursor-search-mcp"
    }
  }
}
```

### OpenAI Codex

```bash
codex mcp add cursor-search -- cursor-search-mcp
```

Or add to `~/.codex/config.toml`:

```toml
[mcp_servers.cursor-search]
command = "cursor-search-mcp"
```

### OpenCode

```bash
opencode mcp add
```

Or add to `opencode.json`:

```json
{
  "mcp": {
    "cursor-search": {
      "type": "local",
      "command": "cursor-search-mcp",
      "enabled": true
    }
  }
}
```

## Config (optional)

- `CURSOR_REPO_NAME` / `CURSOR_REPO_OWNER`
- `CURSOR_WORKSPACE_PATH`
- `CURSOR_ACCESS_TOKEN`
- `CURSOR_CONFIG_PATH`
- `CURSOR_VERSION`

## Tools

- `codebase_search`: semantic search in the index
- `ensure_codebase_indexed`: trigger index creation
- `refresh_repo_info`: refresh repo detection
- `list_indexed_repos`: show locally indexed repos

## Disclaimer

Unofficial project; Cursor may change the API.
