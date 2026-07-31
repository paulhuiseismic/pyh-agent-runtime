import pytest

from kernel.tool import EchoTool, ToolRegistry
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_errors import (
    McpConnectionError,
    McpDisconnectedError,
    McpTimeoutError,
)
from kernel.tool.mcp_tool import McpTool, register_mcp_tools


async def test_connect_bad_stdio_command_raises_connection_error(
    mcp_bad_command_config,
):
    connection = McpServerConnection(mcp_bad_command_config)
    with pytest.raises(McpConnectionError):
        await connection.connect()


async def test_connect_unreachable_http_raises_connection_error(
    mcp_unreachable_http_config,
):
    connection = McpServerConnection(mcp_unreachable_http_config)
    with pytest.raises(McpConnectionError):
        await connection.connect()


async def test_call_timeout_raises_mcp_timeout_error(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    tool = McpTool(name="slow", description="slow tool", connection=connection)
    with pytest.raises(McpTimeoutError):
        await tool.invoke({"seconds": 10.0}, tenant_id="tenant-a")
    await connection.disconnect()


async def test_disconnect_then_invoke_raises_disconnected_error(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    await connection.disconnect()
    with pytest.raises(McpDisconnectedError):
        await connection.call_tool("echo", {"payload": {}})


async def test_never_connected_raises_disconnected_error(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    with pytest.raises(McpDisconnectedError):
        await connection.discover_tools()
    with pytest.raises(McpDisconnectedError):
        await connection.call_tool("echo", {"payload": {}})


async def test_failed_connection_does_not_affect_other_tools(
    mcp_bad_command_config, mcp_stdio_config
):
    registry = ToolRegistry()
    registry.register(EchoTool())

    good_connection = McpServerConnection(mcp_stdio_config)
    await good_connection.connect()
    await register_mcp_tools(good_connection, registry)

    bad_connection = McpServerConnection(mcp_bad_command_config)
    with pytest.raises(McpConnectionError):
        await bad_connection.connect()

    result = await registry.get("echo").invoke({}, tenant_id="tenant-a")
    assert result == "{}"
    slow_tool = registry.get("slow")
    invoke_result = await slow_tool.invoke({"seconds": 0}, tenant_id="tenant-a")
    assert invoke_result == "done"

    await good_connection.disconnect()
