from dataclasses import dataclass
from enum import Enum, auto

from kernel.provider.errors import InvalidRequestError


class McpConnectionState(Enum):
    NOT_CONNECTED = auto()
    CONNECTED = auto()
    CONNECT_FAILED = auto()
    DISCONNECTED = auto()


@dataclass(frozen=True)
class McpServerConfig:
    transport: str
    command: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    connect_timeout_seconds: float = 10.0
    discover_timeout_seconds: float = 10.0
    call_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.transport not in ("stdio", "http"):
            raise InvalidRequestError(
                f"transport must be 'stdio' or 'http', got {self.transport!r}"
            )
        if self.transport == "stdio" and not self.command:
            raise InvalidRequestError("stdio transport requires a non-empty command")
        if self.transport == "http" and not self.url:
            raise InvalidRequestError("http transport requires a url")
        for field_name in (
            "connect_timeout_seconds",
            "discover_timeout_seconds",
            "call_timeout_seconds",
        ):
            value = getattr(self, field_name)
            if value <= 0:
                raise InvalidRequestError(f"{field_name} must be > 0, got {value}")


@dataclass(frozen=True)
class DiscoveredMcpTool:
    name: str
    description: str
    input_schema: dict
