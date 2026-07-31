from kernel.tool import EchoTool, ToolRegistry
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_tool import register_mcp_tools


async def test_conflicting_tool_name_skipped_others_registered(mcp_stdio_config):
    registry = ToolRegistry()
    existing = EchoTool()
    registry.register(existing)

    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect()
    result = await register_mcp_tools(connection, registry)

    assert "echo" not in result.registered
    assert any(name == "echo" for name, _reason in result.skipped)
    assert "slow" in result.registered
    assert "fail" in result.registered
    assert registry.get("echo") is existing

    await connection.disconnect()
