"""平台服务层：REST 入口 + AgentService（组合 001-006 内核能力）。

契约见 specs/007-platform-web-service/contracts/agent-run-api.md。
"""

from platform_service.agent_service import AgentService, build_agent_service
from platform_service.app import create_app
from platform_service.cli import main as cli_main
from platform_service.config import PlatformConfig, TenantConfig
from platform_service.errors import (
    AuthenticationError,
    ConcurrencyLimitExceededError,
    RequestTimeoutError,
)
from platform_service.models import AgentRunRequest, AgentRunResult

__all__ = [
    "AgentService",
    "build_agent_service",
    "create_app",
    "cli_main",
    "PlatformConfig",
    "TenantConfig",
    "AgentRunRequest",
    "AgentRunResult",
    "AuthenticationError",
    "ConcurrencyLimitExceededError",
    "RequestTimeoutError",
]
