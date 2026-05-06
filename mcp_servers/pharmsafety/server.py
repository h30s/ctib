"""PharmSafety-MCP — FastAPI + MCP SDK server.

Exposes medication reconciliation and interaction detection tools.
"""
import os
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from mcp_servers.pharmsafety.tools import reconcile_medications, detect_interactions

mcp = FastMCP("PharmSafety-MCP", json_response=True)

# Register tools with MCP decorator
mcp.tool()(reconcile_medications)
mcp.tool()(detect_interactions)


if __name__ == "__main__":
    load_dotenv()
    mcp.run(transport="streamable-http", port=int(os.getenv("PHARMSAFETY_MCP_PORT", 9001)))
