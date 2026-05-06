"""Dissonance-MCP — FastAPI + MCP SDK server.

Exposes cross-signal conflict detection and severity classification.
"""
import os
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from mcp_servers.dissonance.tools import detect_cross_signal_conflicts, classify_conflict_severity

mcp = FastMCP("Dissonance-MCP", json_response=True)

# Register tools with MCP decorator
mcp.tool()(detect_cross_signal_conflicts)
mcp.tool()(classify_conflict_severity)


if __name__ == "__main__":
    load_dotenv()
    mcp.run(transport="streamable-http", port=int(os.getenv("DISSONANCE_MCP_PORT", 9005)))
