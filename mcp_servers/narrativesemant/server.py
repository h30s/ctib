"""NarrativeSemant-MCP — FastAPI + MCP SDK server.

Exposes clinical assertion extraction, uncertainty detection, and orphaned intention identification.
The purest AI node in CTIB.
"""
import os
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

from mcp_servers.narrativesemant.tools import (
    extract_clinical_assertions, detect_uncertainty_language, identify_open_questions,
)

mcp = FastMCP("NarrativeSemant-MCP", json_response=True)

# Register tools with MCP decorator
mcp.tool()(extract_clinical_assertions)
mcp.tool()(detect_uncertainty_language)
mcp.tool()(identify_open_questions)


if __name__ == "__main__":
    load_dotenv()
    mcp.run(transport="streamable-http", port=int(os.getenv("NARRATIVESEMANT_MCP_PORT", 9003)))
