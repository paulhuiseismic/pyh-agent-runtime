from dataclasses import dataclass, field

from kernel.provider.errors import InvalidRequestError
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_errors import McpDisconnectedError, McpTimeoutError, McpToolExecutionError
from kernel.tool.registry import ToolRegistry
from kernel.tool.telemetry import tool_invoke_span


class McpTool:
    def __init__(
        self, *, name: str, description: str, connection: McpServerConnection
    ) -> None:
        self.name = name
        self.description = description
        self._connection = connection

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        with tool_invoke_span(tenant_id=tenant_id, tool_name=self.name) as span:
            try:
                result = await self._connection.call_tool(self.name, arguments)
            except McpTimeoutError:
                span.set_result_type("timeout")
                raise
            except McpDisconnectedError:
                span.set_result_type("disconnected")
                raise
            except McpToolExecutionError:
                span.set_result_type("tool_execution_failed")
                raise
            span.set_result_type("success")
            return result


@dataclass
class RegisterMcpToolsResult:
    registered: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


async def register_mcp_tools(
    connection: McpServerConnection, registry: ToolRegistry
) -> RegisterMcpToolsResult:
    result = RegisterMcpToolsResult()
    discovered = await connection.discover_tools()
    for tool in discovered:
        mcp_tool = McpTool(
            name=tool.name, description=tool.description, connection=connection
        )
        try:
            registry.register(mcp_tool)
        except InvalidRequestError as exc:
            result.skipped.append((tool.name, str(exc)))
            continue
        result.registered.append(tool.name)
    return result
