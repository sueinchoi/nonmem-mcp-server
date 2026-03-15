"""Entry point for the NONMEM MCP server."""

import asyncio

from mcp.server.stdio import stdio_server

from nonmem_mcp.server import server


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
