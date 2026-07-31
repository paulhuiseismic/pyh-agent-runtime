import asyncio
from contextlib import AsyncExitStack

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

        stack = AsyncExitStack()

        async def _do_connect() -> ClientSession:
            if self._config.transport == "stdio":
                params = StdioServerParameters(
                    command=self._config.command[0],
                    args=list(self._config.command[1:]),
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                http_client = None
                if self._config.headers:
                    http_client = httpx2.AsyncClient(headers=self._config.headers)
                    await stack.enter_async_context(http_client)
                streams = await stack.enter_async_context(
                    streamable_http_client(self._config.url, http_client=http_client)
                )
                read, write = streams[0], streams[1]

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return session

        try:
            self._session = await asyncio.wait_for(
                _do_connect(), timeout=self._config.connect_timeout_seconds
            )
        except asyncio.TimeoutError:
            await stack.aclose()
            self._state = McpConnectionState.CONNECT_FAILED
            raise McpTimeoutError("connect", self._config.connect_timeout_seconds)
        except Exception as exc:
            await stack.aclose()
            self._state = McpConnectionState.CONNECT_FAILED
            raise McpConnectionError(str(exc)) from exc

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
