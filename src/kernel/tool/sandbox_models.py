"""沙箱配置与异常层级（见 specs/005 data-model.md，research.md R5）。"""

from dataclasses import dataclass

from kernel.provider.errors import InvalidRequestError

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_CPU_SECONDS = 10.0
DEFAULT_MAX_MEMORY_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 1 * 1024 * 1024


def _require_positive(name: str, value) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InvalidRequestError(f"SandboxLimits.{name} 必须是数值，收到: {value!r}")
    if value <= 0:
        raise InvalidRequestError(f"SandboxLimits.{name} 必须是正数，收到: {value!r}")


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_cpu_seconds: float = DEFAULT_MAX_CPU_SECONDS
    max_memory_bytes: int = DEFAULT_MAX_MEMORY_BYTES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        _require_positive("timeout_seconds", self.timeout_seconds)
        _require_positive("max_cpu_seconds", self.max_cpu_seconds)
        _require_positive("max_memory_bytes", self.max_memory_bytes)
        _require_positive("max_output_bytes", self.max_output_bytes)


class SandboxError(Exception):
    """沙箱相关失败的基类。"""


class SandboxInfraError(SandboxError):
    """沙箱层面的基础设施失败（超时/资源超限/启动失败）。"""


class SandboxTimeoutError(SandboxInfraError):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"沙箱执行超过显式超时 {timeout_seconds}s，已强制终止")


class SandboxResourceExceededError(SandboxInfraError):
    def __init__(self, resource_name: str, limit):
        self.resource_name = resource_name
        self.limit = limit
        super().__init__(f"沙箱执行超过资源上限（{resource_name}: {limit}），已被终止")


class SandboxStartupError(SandboxInfraError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"沙箱子进程启动失败: {detail}")


class SandboxToolExecutionError(SandboxError):
    """工具自身的业务失败：子进程正常运行但以非零退出码结束。"""

    def __init__(self, exit_code: int, stderr_snippet: str):
        self.exit_code = exit_code
        self.stderr_snippet = stderr_snippet
        super().__init__(f"工具以非零退出码 {exit_code} 结束: {stderr_snippet}")
