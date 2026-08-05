from dataclasses import dataclass, field

from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import Limits, PriceTable
from kernel.tool import McpServerConfig


@dataclass(frozen=True)
class TenantConfig:
    api_key: str
    tenant_id: str
    max_concurrent_requests: int

    def __post_init__(self) -> None:
        if not self.api_key:
            raise InvalidRequestError("tenant.api_key 必填且不能为空")
        if not self.tenant_id:
            raise InvalidRequestError("tenant.tenant_id 必填且不能为空")
        if self.max_concurrent_requests <= 0:
            raise InvalidRequestError(
                f"tenant.max_concurrent_requests 必须 > 0，"
                f"收到: {self.max_concurrent_requests!r}"
            )


@dataclass(frozen=True)
class PlatformConfig:
    tenants: list[TenantConfig]
    global_max_concurrent_requests: int
    request_timeout_seconds: float
    model: str
    max_steps: int
    provider_base_url: str
    price_table: PriceTable
    provider_api_key: str | None = None
    provider_call_limits: Limits | None = None
    mcp_servers: list[McpServerConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.global_max_concurrent_requests <= 0:
            raise InvalidRequestError(
                "platform.global_max_concurrent_requests 必须 > 0，"
                f"收到: {self.global_max_concurrent_requests!r}"
            )
        if self.request_timeout_seconds <= 0:
            raise InvalidRequestError(
                "platform.request_timeout_seconds 必须 > 0，"
                f"收到: {self.request_timeout_seconds!r}"
            )
        if not self.model:
            raise InvalidRequestError("platform.model 必填且不能为空")
        if self.max_steps <= 0:
            raise InvalidRequestError(
                f"platform.max_steps 必须 > 0，收到: {self.max_steps!r}"
            )
        if not self.provider_base_url:
            raise InvalidRequestError("platform.provider_base_url 必填且不能为空")

        # 触发一次单价查询：模型未配置单价时 PriceTable.price_for() 会抛
        # InvalidRequestError（001 既有行为），这里在启动期主动校验一次，
        # 而不是等到第一次请求才发现（FR-013/FR-014）。
        self.price_table.price_for(self.model)

        api_keys = [t.api_key for t in self.tenants]
        if len(api_keys) != len(set(api_keys)):
            raise InvalidRequestError("tenants 中存在重复的 api_key")
        tenant_ids = [t.tenant_id for t in self.tenants]
        if len(tenant_ids) != len(set(tenant_ids)):
            raise InvalidRequestError("tenants 中存在重复的 tenant_id")
