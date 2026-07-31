import asyncio
from contextlib import AsyncExitStack
from urllib.parse import urlsplit

import httpx2
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from kernel.tool.mcp_errors import (
    McpConnectionError,
    McpDisconnectedError,
    McpTimeoutError,
    McpToolExecutionError,
)
from kernel.tool.mcp_models import DiscoveredMcpTool, McpConnectionState, McpServerConfig


async def _preflight_tcp_check(url: str, timeout_seconds: float) -> None:
    """在进入 streamable_http_client 之前先探测 TCP 可达性。

    直接把"连接被拒绝/不可达"交给 streamable_http_client 内部的
    anyio 任务组处理，在该 SDK 版本下会在清理阶段触发
    "exit cancel scope in a different task" 的内部错误（连接建立失败发生在
    其内部任务组尚未 yield 时）。用一次独立的、不涉及任务组的 TCP 探测
    提前捕获同类失败，避免触发该问题（research.md R7）。
    """
    parsed = urlsplit(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=timeout_seconds
    )
    writer.close()
    await writer.wait_closed()


class McpServerConnection:
    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._state = McpConnectionState.NOT_CONNECTED
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @property
    def state(self) -> McpConnectionState:
        return self._state

    async def connect(self) -> None:
        if self._state == McpConnectionState.CONNECTED:
            return
        if self._state in (
            McpConnectionState.CONNECT_FAILED,
            McpConnectionState.DISCONNECTED,
        ):
            raise McpConnectionError(
                "connection already used and cannot be retried in place; "
                "create a new McpServerConnection instance"
            )

        # AsyncExitStack entries and their later exit (disconnect()/failure
        # cleanup) must happen in the same asyncio Task — anyio's cancel
        # scopes (used internally by stdio_client/streamable_http_client/
        # ClientSession) are task-bound. Wrapping the whole entry sequence
        # in asyncio.wait_for would run it in a separate spawned Task,
        # causing "exit cancel scope in a different task" errors when
        # cleanup later runs in the caller's task (research.md R7 finding).
        # Only the single non-context-manager await (session.initialize())
        # is wrapped in a timeout.
        stack = AsyncExitStack()
        try:
            if self._config.transport == "stdio":
                params = StdioServerParameters(
                    command=self._config.command[0],
                    args=list(self._config.command[1:]),
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                await _preflight_tcp_check(
                    self._config.url, self._config.connect_timeout_seconds
                )
                http_client = httpx2.AsyncClient(
                    headers=self._config.headers,
                    timeout=self._config.connect_timeout_seconds,
                )
                await stack.enter_async_context(http_client)
                streams = await stack.enter_async_context(
                    streamable_http_client(self._config.url, http_client=http_client)
                )
                read, write = streams[0], streams[1]

            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(
                session.initialize(), timeout=self._config.connect_timeout_seconds
            )
        except asyncio.TimeoutError:
            await stack.aclose()
            self._state = McpConnectionState.CONNECT_FAILED
            raise McpTimeoutError("connect", self._config.connect_timeout_seconds)
        except Exception as exc:
            await stack.aclose()
            self._state = McpConnectionState.CONNECT_FAILED
            raise McpConnectionError(str(exc)) from exc

        self._session = session
        self._exit_stack = stack
        self._state = McpConnectionState.CONNECTED

    async def discover_tools(self) -> list[DiscoveredMcpTool]:
        if self._state != McpConnectionState.CONNECTED:
            raise McpDisconnectedError(
                f"connection state is {self._state.name}, not CONNECTED"
            )
        try:
            result = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self._config.discover_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise McpTimeoutError("discover", self._config.discover_timeout_seconds)
        except Exception as exc:
            self._state = McpConnectionState.DISCONNECTED
            raise McpDisconnectedError(str(exc)) from exc

        return [
            DiscoveredMcpTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self._state != McpConnectionState.CONNECTED:
            raise McpDisconnectedError(
                f"connection state is {self._state.name}, not CONNECTED"
            )
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=self._config.call_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise McpTimeoutError("call", self._config.call_timeout_seconds)
        except Exception as exc:
            self._state = McpConnectionState.DISCONNECTED
            raise McpDisconnectedError(str(exc)) from exc

        text = "".join(
            part.text for part in result.content if hasattr(part, "text")
        )
        if result.is_error:
            raise McpToolExecutionError(name, text)
        return text

    async def disconnect(self) -> None:
        if self._state != McpConnectionState.CONNECTED:
            self._state = McpConnectionState.DISCONNECTED
            return
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._session = None
        self._state = McpConnectionState.DISCONNECTED
