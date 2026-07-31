"""tool 测试公共设施：示例脚本路径、短超时 SandboxLimits fixture、
MCP 测试用 server 命令/配置 fixture。"""

import asyncio
import socket
import sys
from pathlib import Path

import pytest

from kernel.tool.mcp_models import McpServerConfig
from kernel.tool.sandbox_models import SandboxLimits

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_MCP_FIXTURES_DIR = Path(__file__).parent / "mcp_fixtures"


def _script_command(script_name: str) -> list[str]:
    return [sys.executable, str(_FIXTURES_DIR / script_name)]


@pytest.fixture
def echo_args_command() -> list[str]:
    return _script_command("echo_args.py")


@pytest.fixture
def sleep_forever_command() -> list[str]:
    return _script_command("sleep_forever.py")


@pytest.fixture
def exit_nonzero_command() -> list[str]:
    return _script_command("exit_nonzero.py")


@pytest.fixture
def grow_memory_command() -> list[str]:
    return _script_command("grow_memory.py")


@pytest.fixture
def short_timeout_limits() -> SandboxLimits:
    """供超时类测试使用的较小 timeout_seconds，加速测试执行。"""
    return SandboxLimits(timeout_seconds=0.3)


def _mcp_script_command(script_name: str) -> list[str]:
    return [sys.executable, str(_MCP_FIXTURES_DIR / script_name)]


@pytest.fixture
def mcp_stdio_command() -> list[str]:
    return _mcp_script_command("test_server.py")


@pytest.fixture
def mcp_empty_stdio_command() -> list[str]:
    return _mcp_script_command("empty_server.py")


@pytest.fixture
def mcp_stdio_config(mcp_stdio_command) -> McpServerConfig:
    return McpServerConfig(
        transport="stdio",
        command=mcp_stdio_command,
        connect_timeout_seconds=5.0,
        discover_timeout_seconds=5.0,
        call_timeout_seconds=2.0,
    )


@pytest.fixture
def mcp_empty_stdio_config(mcp_empty_stdio_command) -> McpServerConfig:
    return McpServerConfig(
        transport="stdio",
        command=mcp_empty_stdio_command,
        connect_timeout_seconds=5.0,
        discover_timeout_seconds=5.0,
        call_timeout_seconds=2.0,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mcp_bad_command_config() -> McpServerConfig:
    """指向一个不存在的可执行文件，供连接失败场景使用。"""
    return McpServerConfig(
        transport="stdio",
        command=["nonexistent-mcp-server-command-xyz"],
        connect_timeout_seconds=5.0,
    )


@pytest.fixture
def mcp_unreachable_http_config() -> McpServerConfig:
    """指向一个未监听的本地端口，供连接失败场景使用。"""
    return McpServerConfig(
        transport="http",
        url=f"http://127.0.0.1:{_free_port()}/mcp",
        connect_timeout_seconds=2.0,
    )


@pytest.fixture
async def mcp_http_server():
    """在测试内以后台 asyncio.Task 启动 test_server.py 的 MCPServer 实例
    （streamable-http 模式，research.md R7），yield 对应的 McpServerConfig，
    测试结束后取消后台任务。"""
    sys.path.insert(0, str(_MCP_FIXTURES_DIR))
    try:
        from test_server import mcp as mcp_server
    finally:
        sys.path.remove(str(_MCP_FIXTURES_DIR))

    port = _free_port()
    task = asyncio.create_task(
        mcp_server.run_streamable_http_async(host="127.0.0.1", port=port)
    )
    await asyncio.sleep(0.5)  # 等待 server 启动监听
    try:
        yield McpServerConfig(
            transport="http",
            url=f"http://127.0.0.1:{port}/mcp",
            connect_timeout_seconds=5.0,
            discover_timeout_seconds=5.0,
            call_timeout_seconds=2.0,
        )
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
