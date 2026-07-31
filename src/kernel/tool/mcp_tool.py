from dataclasses import dataclass, field

from kernel.provider.errors import InvalidRequestError
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.registry import ToolRegistry


class McpTool:
    def __init__(
        self, *, name: str, description: str, connection: McpServerConnection
    ) -> None:
        self.name = name
        self.description = description
        self._connection = connection

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        return await self._connection.call_tool(self.name, arguments)


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
