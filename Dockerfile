# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install dependencies
RUN uv pip install --system --no-cache -e .

# Environment variables (can be overridden at runtime)
ENV CURSOR_REPO_NAME=""
ENV CURSOR_REPO_OWNER=""
ENV CURSOR_WORKSPACE_PATH="/workspace"
ENV CURSOR_ACCESS_TOKEN=""

# Expose default port for HTTP transport
EXPOSE 8000

# Default command runs the MCP server with stdio transport
# Use --transport http --port 8000 for HTTP mode
ENTRYPOINT ["python", "-m", "cursor_search_mcp.server"]
