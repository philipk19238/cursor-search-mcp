# Cursor Search MCP

Expose Cursor's semantic code search through MCP.

## Requirements

- Python 3.10+
- Cursor installed and logged in (once)
- uv or pip

Cursor must index the repo. Open it in Cursor and wait for indexing to finish.

## Install

```bash
git clone https://github.com/philipk19238/cursor-search-mcp.git
cd cursor-search-mcp
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
claude mcp add cursor-search -- \
  env CURSOR_WORKSPACE_PATH=/path/to/your/repo \
  uv run --directory /path/to/cursor-search-mcp cursor-search-mcp
```

Or add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "cursor-search": {
      "command": "env",
      "args": [
        "CURSOR_WORKSPACE_PATH=/path/to/your/repo",
        "uv", "run", "--directory", "/path/to/cursor-search-mcp",
        "cursor-search-mcp"
      ]
    }
  }
}
```

### OpenAI Codex

```bash
codex mcp add cursor-search -- \
  env CURSOR_WORKSPACE_PATH=/path/to/your/repo \
  uv run --directory /path/to/cursor-search-mcp cursor-search-mcp
```

Or add to `~/.codex/config.toml`:

```toml
[mcp_servers.cursor-search]
command = "env"
args = [
  "CURSOR_WORKSPACE_PATH=/path/to/your/repo",
  "uv", "run", "--directory", "/path/to/cursor-search-mcp",
  "cursor-search-mcp"
]
```

### OpenCode

Add to `opencode.json`:

```json
{
  "mcp": {
    "cursor-search": {
      "type": "local",
      "command": "env",
      "args": [
        "CURSOR_WORKSPACE_PATH=/path/to/your/repo",
        "uv", "run", "--directory", "/path/to/cursor-search-mcp",
        "cursor-search-mcp"
      ],
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

If the server is launched outside the repo, set `CURSOR_WORKSPACE_PATH` to the
indexed workspace root. Startup fails if the workspace is not indexed.

## Tools

- `codebase_search`: semantic search in the index
- `ensure_codebase_indexed`: trigger index creation
- `refresh_repo_info`: refresh repo detection
- `list_indexed_repos`: show locally indexed repos

## Acknowledgements

Based on reverse engineering work from:
- [cursor-rpc](https://github.com/everestmz/cursor-rpc) - Go library with protobuf definitions
- [cursor-unchained](https://github.com/dcrebbin/cursor-unchained) - Cursor API reverse engineering

## Disclaimer

Unofficial project; Cursor may change the API.
