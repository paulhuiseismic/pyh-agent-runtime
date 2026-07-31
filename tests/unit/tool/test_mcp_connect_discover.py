from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_models import McpConnectionState


async def test_stdio_connect_success(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    assert connection.state == McpConnectionState.CONNECTED
    await connection.disconnect()


async def test_stdio_discover_tools(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    tools = await connection.discover_tools()
    names = {t.name for t in tools}
    assert names == {"echo", "slow", "fail"}
    for tool in tools:
        assert tool.description is not None
    await connection.disconnect()


async def test_discover_empty_tool_list(mcp_empty_stdio_config):
    connection = McpServerConnection(mcp_empty_stdio_config)
    await connection.connect()
    tools = await connection.discover_tools()
    assert tools == []
    await connection.disconnect()


async def test_repeated_connect_is_noop_when_connected(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    await connection.connect()
    assert connection.state == McpConnectionState.CONNECTED
    tools = await connection.discover_tools()
    assert {t.name for t in tools} == {"echo", "slow", "fail"}
    await connection.disconnect()
