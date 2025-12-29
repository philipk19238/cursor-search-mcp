# Cursor Search MCP

An MCP (Model Context Protocol) server that exposes Cursor's semantic codebase search capabilities to any MCP-compatible client (Claude Desktop, Claude Code, etc.).

## Overview

This server wraps Cursor's internal semantic search API, allowing you to use their powerful vector-based code search from any MCP client. The search finds code by **meaning**, not just exact text matching.

## Prerequisites

- Python 3.10+
- [Cursor](https://cursor.sh) installed and logged in (at least once)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Installation

### Using uv (recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/cursor-search-mcp.git
cd cursor-search-mcp

# Create virtual environment and install
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

### Using pip

```bash
pip install -e .
```

### Using Docker

```bash
# Build the image
docker build -t cursor-search-mcp:latest .

# Run with stdio transport (for MCP clients)
docker run -it --rm \
  -e CURSOR_REPO_NAME=your-repo \
  -e CURSOR_REPO_OWNER=your-username \
  -e CURSOR_ACCESS_TOKEN=your-token \
  cursor-search-mcp:latest

# Or mount your Cursor credentials (macOS)
docker run -it --rm \
  -e CURSOR_REPO_NAME=your-repo \
  -e CURSOR_REPO_OWNER=your-username \
  -v "$HOME/Library/Application Support/Cursor:/root/.cursor:ro" \
  cursor-search-mcp:latest
```

## Configuration

### Auto-Detection (Recommended)

The server **automatically detects** the repository name and owner from the git remote URL! Just run the server from within your git repository - no configuration needed.

```bash
cd /path/to/your/repo
cursor-search-mcp  # Auto-detects owner/repo from git remote
```

Use the `refresh_repo_info` tool to update after switching repositories.

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `CURSOR_REPO_NAME` | Override repository name | No (auto-detected from git) |
| `CURSOR_REPO_OWNER` | Override repository owner | No (auto-detected from git) |
| `CURSOR_WORKSPACE_PATH` | Path to the workspace root | No (auto-detected from git) |
| `CURSOR_ACCESS_TOKEN` | Override Cursor auth token | No (auto-detected) |
| `CURSOR_CONFIG_PATH` | Override Cursor config directory | No (auto-detected) |
| `CURSOR_VERSION` | Cursor client version | No (defaults to 0.50.5) |

### Authentication

The server automatically reads your Cursor credentials from the local database:
- **macOS**: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- **Windows**: `%APPDATA%/Cursor/User/globalStorage/state.vscdb`
- **Linux**: `~/.config/Cursor/User/globalStorage/state.vscdb`

**Note**: You must have logged into Cursor at least once for credentials to exist.

## Usage

### Running the Server

```bash
# Using the installed script
cursor-search-mcp

# Or directly with fastmcp
fastmcp run src/cursor_search_mcp/server.py

# With HTTP transport (for remote access)
fastmcp run src/cursor_search_mcp/server.py --transport http --port 8000
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cursor-search": {
      "command": "cursor-search-mcp",
      "env": {
        "CURSOR_REPO_NAME": "your-repo-name",
        "CURSOR_REPO_OWNER": "your-github-username"
      }
    }
  }
}
```

Or using uv directly:

```json
{
  "mcpServers": {
    "cursor-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cursor-search-mcp", "cursor-search-mcp"],
      "env": {
        "CURSOR_REPO_NAME": "your-repo-name",
        "CURSOR_REPO_OWNER": "your-github-username"
      }
    }
  }
}
```

### Claude Code Configuration

Add the MCP server to Claude Code using the CLI:

```bash
# Using uv (recommended) - auto-detects repo from current directory!
claude mcp add cursor-search -- uv run --directory /path/to/cursor-search-mcp cursor-search-mcp

# Using Docker with mounted credentials (auto-detects everything)
claude mcp add cursor-search -- docker run -i --rm \
  -v "$HOME/Library/Application Support/Cursor:/root/.cursor:ro" \
  -v "$(pwd):/workspace" \
  -w /workspace \
  cursor-search-mcp:latest

# Using Docker with explicit token
claude mcp add cursor-search \
  -e CURSOR_ACCESS_TOKEN=your-token \
  -- docker run -i --rm \
    -e CURSOR_ACCESS_TOKEN \
    -v "$(pwd):/workspace" \
    -w /workspace \
    cursor-search-mcp:latest
```

**Note**: The server auto-detects repo info from git. Use the `refresh_repo_info` tool after switching repos.

Or add to your `~/.claude/settings.json` manually:

```json
{
  "mcpServers": {
    "cursor-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cursor-search-mcp", "cursor-search-mcp"]
    }
  }
}
```

## Tools

### `codebase_search`

Semantic search that finds code by meaning, not exact text.

**When to use:**
- Explore unfamiliar codebases
- Ask "how / where / what" questions to understand behavior
- Find code by meaning rather than exact text

**When NOT to use:**
- Exact text matches (use `grep`)
- Reading known files (use `read_file`)
- Simple symbol lookups (use `grep`)
- Finding files by name (use `file_search`)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | A complete question about what you want to understand |
| `explanation` | string | Why this tool is being used and how it contributes to the goal |
| `target_directories` | string[] | Optional directory paths to limit search scope |

**Examples:**

```python
# Good: Complete question with context
codebase_search(
    query="Where is interface MyInterface implemented in the frontend?",
    explanation="Find implementation location with specific context",
    target_directories=["frontend/"]
)

# Good: Start broad, then narrow down
codebase_search(
    query="How does user authentication work?",
    explanation="Find auth flow in the codebase",
    target_directories=[]
)

# Bad: Too vague
codebase_search(query="MyInterface frontend", ...)  # Use grep instead

# Bad: Multiple questions
codebase_search(query="What is AuthService? How does it work?", ...)  # Split into two calls
```

### `ensure_codebase_indexed`

Ensure the current codebase is indexed for semantic search. Call this before searching if you're unsure whether the codebase has been indexed.

### `refresh_repo_info`

Refresh the repository information by re-detecting from git. Use this after:
- Switching to a different repository
- Changing the git remote
- If search results seem to be from the wrong repo

Returns the updated repository name, owner, and workspace path.

## How It Works

This MCP server reverse-engineers Cursor's internal gRPC API to provide semantic search:

1. **Authentication**: Reads your Cursor credentials from the local SQLite database
2. **Search**: Calls `aiserver.v1.RepositoryService/SearchRepositoryV2` or `SemSearch` endpoints
3. **Results**: Returns ranked code chunks with file paths, line numbers, and relevance scores

### API Endpoints Used

- `https://repo42.cursor.sh` - Repository service (indexing, search)
- `https://api2.cursor.sh` - AI service (embeddings, chat)

### Supported Embedding Models

Cursor uses these models for code embeddings:
- `VOYAGE_CODE_2`
- `TEXT_EMBEDDINGS_LARGE_3`
- `QWEN_1_5B_CUSTOM`

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Format code
ruff format .
ruff check --fix .
```

## Acknowledgements

This project is based on reverse engineering work from:
- [cursor-rpc](https://github.com/everestmz/cursor-rpc) - Go library with full protobuf definitions
- [cursor-unchained](https://github.com/dcrebbin/cursor-unchained) - Tab completion reverse engineering

## License

MIT

## Disclaimer

This is an unofficial project and is not affiliated with or endorsed by Cursor. Use at your own risk. The API may change without notice as Cursor updates their application.
