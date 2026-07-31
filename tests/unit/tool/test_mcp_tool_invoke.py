from kernel.react.engine import ReactEngine
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_tool import McpTool


async def test_invoke_echo_passthrough(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")
    tool = McpTool(name="echo", description="echo tool", connection=connection)
    result = await tool.invoke({"payload": {"a": 1}}, tenant_id="tenant-a")
    assert '"a": 1' in result
    await connection.disconnect(tenant_id="tenant-a")


async def test_mcp_tool_usable_in_react_engine_tools_dict(mcp_stdio_config):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")
    tool = McpTool(name="echo", description="echo tool", connection=connection)

    engine = ReactEngine(provider=None, tools={"echo": tool}, model="stub")
    assert engine._tools["echo"] is tool
    await connection.disconnect(tenant_id="tenant-a")
