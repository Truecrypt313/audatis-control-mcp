"""Absolute-path friendly entry point for the independent Consulting MCP server."""
from isms_copilot.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
