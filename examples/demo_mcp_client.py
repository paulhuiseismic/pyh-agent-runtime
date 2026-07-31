"""T028: MCP 客户端接入演示——stdio/HTTP 连接发现调用、超时、业务失败、
断开后失败隔离。

运行: python examples/demo_mcp_client.py（无需网络与真实 MCP server 部署，
测试用 server 由本脚本自行以子进程/后台任务方式启动）
预期输出见 specs/006-mcp-client-integration/quickstart.md 第 2 节。
"""

import asyncio
import socket
import sys
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.tool import ToolRegistry
from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_errors import (
    McpDisconnectedError,
    McpTimeoutError,
    McpToolExecutionError,
)
from kernel.tool.mcp_models import McpServerConfig
from kernel.tool.mcp_tool import McpTool, register_mcp_tools

_MCP_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "unit" / "tool" / "mcp_fixtures"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def main() -> None:
    setup_console_tracing()
    registry = ToolRegistry()

    print("=== 1. stdio 传输：连接、发现、注册 ===")
    stdio_config = McpServerConfig(
        transport="stdio",
        command=[sys.executable, str(_MCP_FIXTURES_DIR / "test_server.py")],
        call_timeout_seconds=2.0,
    )
    stdio_connection = McpServerConnection(stdio_config)
    await stdio_connection.connect(tenant_id="tenant-demo")
    result = await register_mcp_tools(stdio_connection, registry)
    print(f"已注册: {result.registered}，跳过: {result.skipped}\n")

    print("=== 2. 调用 echo 工具（stdio）===")
    echo_result = await registry.get("echo").invoke(
        {"payload": {"hello": "world"}}, tenant_id="tenant-demo"
    )
    print(f"结果: {echo_result}\n")

    print("=== 3. HTTP 传输：连接、发现、调用，行为与 stdio 等价 ===")
    sys.path.insert(0, str(_MCP_FIXTURES_DIR))
    from test_server import mcp as http_server_instance

    port = _free_port()
    server_task = asyncio.create_task(
        http_server_instance.run_streamable_http_async(host="127.0.0.1", port=port)
    )
    await asyncio.sleep(0.5)
    http_config = McpServerConfig(
        transport="http",
        url=f"http://127.0.0.1:{port}/mcp",
        call_timeout_seconds=2.0,
    )
    http_connection = McpServerConnection(http_config)
    await http_connection.connect(tenant_id="tenant-demo")
    http_tool = McpTool(name="echo", description="echo tool", connection=http_connection)
    http_result = await http_tool.invoke({"payload": {"via": "http"}}, tenant_id="tenant-demo")
    print(f"HTTP 调用结果: {http_result}\n")

    print("=== 4. 调用 slow 工具触发超时 ===")
    try:
        await registry.get("slow").invoke({"seconds": 10.0}, tenant_id="tenant-demo")
    except McpTimeoutError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("=== 5. 调用 fail 工具触发业务失败 ===")
    try:
        await registry.get("fail").invoke({}, tenant_id="tenant-demo")
    except McpToolExecutionError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("=== 6. 主动断开 HTTP 连接后调用失败，stdio 连接不受影响 ===")
    # 注意：多个 McpServerConnection 在同一 asyncio 任务内建立时，底层 anyio
    # 取消作用域按 LIFO 顺序绑定到该任务；disconnect() 必须按与 connect() 相反
    # 的顺序调用（此处 http 后连接、先断开），否则会触发 anyio 内部的
    # cancel-scope 顺序错误（research.md R9，实现阶段发现的真实约束）。
    await http_connection.disconnect(tenant_id="tenant-demo")
    try:
        await http_tool.invoke({"payload": {}}, tenant_id="tenant-demo")
    except McpDisconnectedError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}")
    still_works = await registry.get("echo").invoke(
        {"payload": {"still": "alive"}}, tenant_id="tenant-demo"
    )
    print(f"stdio 连接的工具仍可正常调用: {still_works}\n")

    await stdio_connection.disconnect(tenant_id="tenant-demo")
    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass

    print("演示完成：每次 connect()/disconnect() 产生 mcp.connect/mcp.disconnect "
          "span，每次 invoke() 产生 tool.invoke span（含 tenant_id/transport/"
          "tool_name/result_type，见控制台 JSON 输出）。")


if __name__ == "__main__":
    asyncio.run(main())
