"""Official MCP CLI call to trusted import/build wrappers and the isolated Gemini worker."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(config_path):
    config = json.loads(Path(config_path).read_text())
    params = StdioServerParameters(
        command=config["command"],
        env={
            **os.environ,
            "BLENDER_PATH": config["binary"],
            "BLENDER_MCP_HOST": "127.0.0.1",
            "BLENDER_MCP_PORT": "9876",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=config["timeout"])
        ) as session:
            await session.initialize()
            response = await session.call_tool(
                "execute_blender_code_for_cli",
                {"blend_file": config["seed"], "code": config["code"]},
            )
            if response.isError:
                raise RuntimeError("Blender MCP execution failed: " + str(response.content))
            Path(config["receipt"]).write_text(json.dumps(response.model_dump(mode="json")))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
