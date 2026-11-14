"""Independent stdio server. Does NOT register tools in or start the base server."""
from mcp.server import MCPServer

from .tools import register_copilot_tools

mcp = MCPServer("ISMS Consulting Copilot")
register_copilot_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="stdio")
