"""tool 模块公共接口（契约见 specs/005 contracts/tool-registry-sandbox-api.md）。

Tool Protocol 签名冻结于 001/002，本 feature 不得修改。
"""

from kernel.tool.protocol import Tool
from kernel.tool.registry import ToolRegistry
from kernel.tool.sandbox import SandboxedTool
from kernel.tool.sandbox_models import (
    SandboxError,
    SandboxInfraError,
    SandboxLimits,
    SandboxResourceExceededError,
    SandboxStartupError,
    SandboxTimeoutError,
    SandboxToolExecutionError,
)


class EchoTool:
    """占位实现：原样返回入参，仅锁定接口签名（001 交付，保留）。"""

    name = "echo"
    description = "占位工具：原样返回 arguments 的字符串表示"

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        return str(arguments)


__all__ = [
    "Tool",
    "EchoTool",
    "ToolRegistry",
    "SandboxedTool",
    "SandboxLimits",
    "SandboxError",
    "SandboxInfraError",
    "SandboxTimeoutError",
    "SandboxResourceExceededError",
    "SandboxStartupError",
    "SandboxToolExecutionError",
]
