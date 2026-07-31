"""测试用 MCP server：暴露 echo/slow/fail 三个工具，供 006 的 stdio/HTTP 传输
单元测试与集成测试驱动。可直接作为 stdio 子进程执行，也可在测试进程内以
streamable-http 模式启动（见 tests/unit/tool/conftest.py 的 mcp_http_server fixture）。
"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("test-server")


@mcp.tool()
def echo(payload: dict) -> dict:
    return payload


@mcp.tool()
async def slow(seconds: float) -> str:
    import asyncio

    await asyncio.sleep(seconds)
    return "done"


@mcp.tool()
def fail() -> str:
    raise RuntimeError("intentional failure for testing")


if __name__ == "__main__":
    mcp.run(transport="stdio")
