"""PopulationSignal-MCP — FastAPI + MCP SDK server.

Exposes trajectory archetype matching. Deterministic — no LLM.
"""
import os
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from mcp_servers.populationsignal.tools import match_trajectory_archetype

mcp = FastMCP("PopulationSignal-MCP", json_response=True)

# Register tool with MCP decorator
mcp.tool()(match_trajectory_archetype)


if __name__ == "__main__":
    load_dotenv()
    mcp.run(transport="streamable-http", port=int(os.getenv("POPULATIONSIGNAL_MCP_PORT", 9004)))
