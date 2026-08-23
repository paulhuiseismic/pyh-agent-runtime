"""平台服务层：REST 入口 + AgentService（组合 001-006 内核能力）。

契约见 specs/007-platform-web-service/contracts/agent-run-api.md。
"""

from platform_service.agent_service import AgentService, build_agent_service
from platform_service.app import create_app
from platform_service.audit import AuditEntry, AuditStore, UsageSummary
from platform_service.cli import main as cli_main
from platform_service.config import ChannelConfig, PlatformConfig, TenantConfig
from platform_service.errors import (
    AuthenticationError,
    ChannelNotFoundError,
    ConcurrencyLimitExceededError,
    QuotaExceededError,
    RequestTimeoutError,
)
from platform_service.message_gateway import MessageGateway, build_message_gateway
from platform_service.models import (
    AgentRunRequest,
    AgentRunResult,
    InboundAcceptResult,
    InboundMessage,
)

__all__ = [
    "AgentService",
    "build_agent_service",
    "create_app",
    "cli_main",
    "AuditStore",
    "AuditEntry",
    "UsageSummary",
    "ChannelConfig",
    "PlatformConfig",
    "TenantConfig",
    "AgentRunRequest",
    "AgentRunResult",
    "InboundMessage",
    "InboundAcceptResult",
    "MessageGateway",
    "build_message_gateway",
    "AuthenticationError",
    "ChannelNotFoundError",
    "ConcurrencyLimitExceededError",
    "QuotaExceededError",
    "RequestTimeoutError",
]
