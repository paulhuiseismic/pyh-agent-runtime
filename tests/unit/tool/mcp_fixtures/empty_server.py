"""测试用 MCP server：不暴露任何工具，供 006 的"空工具列表"边界场景测试
（spec Edge Cases 第 3 条）。"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("empty-test-server")

if __name__ == "__main__":
    mcp.run(transport="stdio")
