"""VitalsTrend-MCP — FastAPI + MCP SDK server.

Exposes NEWS2 trajectory, subtle deterioration detection, and watch subscription tools.
"""
import os
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from mcp_servers.vitalstrend.tools import (
    compute_news2_trajectory, detect_subtle_deterioration, generate_watch_subscriptions,
)

mcp = FastMCP("VitalsTrend-MCP", json_response=True)

# Register tools with MCP decorator
mcp.tool()(compute_news2_trajectory)
mcp.tool()(detect_subtle_deterioration)
mcp.tool()(generate_watch_subscriptions)


if __name__ == "__main__":
    load_dotenv()
    mcp.run(transport="streamable-http", port=int(os.getenv("VITALSTREND_MCP_PORT", 9002)))
