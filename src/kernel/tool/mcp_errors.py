class McpError(Exception):
    pass


class McpConnectionError(McpError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"MCP connection failed: {detail}")


class McpTimeoutError(McpError):
    def __init__(self, stage: str, timeout_seconds: float) -> None:
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"MCP {stage} timed out after {timeout_seconds}s"
        )


class McpDisconnectedError(McpError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"MCP connection unavailable: {detail}")


class McpToolExecutionError(McpError):
    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"MCP tool '{tool_name}' execution failed: {detail}")
