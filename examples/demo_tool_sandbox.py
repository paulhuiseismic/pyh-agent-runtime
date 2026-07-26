"""T027: tool 注册与沙箱执行 stub 演示——重名拒绝/正常执行/超时/非零退出码。

运行: python examples/demo_tool_sandbox.py（无需网络与真实模型密钥）
预期输出见 specs/005-tool-plugin-sandbox/quickstart.md 第 2 节。
"""

import asyncio
import sys
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.provider.errors import InvalidRequestError
from kernel.tool import EchoTool, SandboxedTool, SandboxLimits, SandboxError
from kernel.tool.registry import ToolRegistry

_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "unit" / "tool" / "fixtures"


def _script_command(script_name: str) -> list[str]:
    return [sys.executable, str(_FIXTURES_DIR / script_name)]


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


async def main() -> None:
    setup_console_tracing()

    print("=== 1. 注册可信工具与沙箱工具 ===")
    registry = ToolRegistry()
    echo_tool = EchoTool()
    sandbox_tool = SandboxedTool(
        name="echo-sandbox", description="沙箱化的 echo 工具",
        command=_script_command("echo_args.py"),
    )
    registry.register(echo_tool)
    registry.register(sandbox_tool)
    print(f"已注册工具: {[t.name for t in registry.list_tools()]}\n")

    print("=== 2. 重复注册同名工具被拒绝 ===")
    try:
        registry.register(SandboxedTool(name="echo", description="dup", command=[]))
    except InvalidRequestError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("=== 3. 沙箱正常执行 ===")
    result = await sandbox_tool.invoke({"query": "hello"}, tenant_id="tenant-demo")
    print(f"结果: {result}\n")

    print("=== 4. 沙箱超时（timeout=0.5s，目标脚本会 sleep 很久）===")
    slow_tool = SandboxedTool(
        name="slow", description="慢工具",
        command=_script_command("sleep_forever.py"),
        limits=SandboxLimits(timeout_seconds=0.5),
    )
    try:
        await slow_tool.invoke({}, tenant_id="tenant-demo")
    except SandboxError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("=== 5. 非零退出码（工具业务失败）===")
    fail_tool = SandboxedTool(
        name="fail", description="失败工具", command=_script_command("exit_nonzero.py"),
    )
    try:
        await fail_tool.invoke({}, tenant_id="tenant-demo")
    except SandboxError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("演示完成：每次 invoke() 各产生一条 tool.invoke span"
          "（含 tenant_id/tool_name/result_type/duration_seconds，见控制台 JSON 输出）。")


if __name__ == "__main__":
    asyncio.run(main())
