from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_models import McpConnectionState
from kernel.tool.mcp_tool import McpTool


async def test_http_connect_and_discover(mcp_http_server):
    connection = McpServerConnection(mcp_http_server)
    await connection.connect(tenant_id="tenant-a")
    assert connection.state == McpConnectionState.CONNECTED

    tools = await connection.discover_tools()
    names = {t.name for t in tools}
    assert names == {"echo", "slow", "fail"}
    await connection.disconnect(tenant_id="tenant-a")


async def test_http_invoke_equivalent_to_stdio(mcp_http_server):
    connection = McpServerConnection(mcp_http_server)
    await connection.connect(tenant_id="tenant-a")
    tool = McpTool(name="echo", description="echo tool", connection=connection)
    result = await tool.invoke({"payload": {"x": 42}}, tenant_id="tenant-a")
    assert '"x": 42' in result
    await connection.disconnect(tenant_id="tenant-a")
