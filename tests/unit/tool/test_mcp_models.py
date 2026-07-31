import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.tool.mcp_errors import (
    McpConnectionError,
    McpDisconnectedError,
    McpTimeoutError,
    McpToolExecutionError,
)
from kernel.tool.mcp_models import McpServerConfig


def test_default_timeouts():
    config = McpServerConfig(transport="stdio", command=["python", "server.py"])
    assert config.connect_timeout_seconds == 10.0
    assert config.discover_timeout_seconds == 10.0
    assert config.call_timeout_seconds == 30.0


def test_stdio_requires_command():
    with pytest.raises(InvalidRequestError):
        McpServerConfig(transport="stdio", command=None)
    with pytest.raises(InvalidRequestError):
        McpServerConfig(transport="stdio", command=[])


def test_http_requires_url():
    with pytest.raises(InvalidRequestError):
        McpServerConfig(transport="http", url=None)


def test_invalid_transport():
    with pytest.raises(InvalidRequestError):
        McpServerConfig(transport="ftp", command=["x"])


@pytest.mark.parametrize(
    "field_name",
    ["connect_timeout_seconds", "discover_timeout_seconds", "call_timeout_seconds"],
)
def test_non_positive_timeout_rejected(field_name):
    kwargs = {"transport": "stdio", "command": ["python", "server.py"], field_name: 0}
    with pytest.raises(InvalidRequestError):
        McpServerConfig(**kwargs)


def test_mcp_connection_error_detail():
    err = McpConnectionError("boom")
    assert err.detail == "boom"


def test_mcp_timeout_error_fields():
    err = McpTimeoutError("connect", 5.0)
    assert err.stage == "connect"
    assert err.timeout_seconds == 5.0


def test_mcp_disconnected_error_detail():
    err = McpDisconnectedError("gone")
    assert err.detail == "gone"


def test_mcp_tool_execution_error_fields():
    err = McpToolExecutionError("echo", "bad input")
    assert err.tool_name == "echo"
    assert err.detail == "bad input"
