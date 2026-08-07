import json
from dataclasses import dataclass, field

from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import Limits, ModelPrice, PriceTable
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
class ChannelConfig:
    channel_id: str
    tenant_id: str
    callback_url: str
    callback_secret: str | None = None

    def __post_init__(self) -> None:
        if not self.channel_id:
            raise InvalidRequestError("channel.channel_id 必填且不能为空")
        if not self.tenant_id:
            raise InvalidRequestError("channel.tenant_id 必填且不能为空")
        if not self.callback_url:
            raise InvalidRequestError("channel.callback_url 必填且不能为空")


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
    session_memory_db_path: str = "platform_sessions.db"
    long_term_memory_db_path: str = "platform_long_term.db"
    channels: list[ChannelConfig] = field(default_factory=list)
    callback_timeout_seconds: float = 10.0
    callback_max_retries: int = 3

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

        if self.callback_timeout_seconds <= 0:
            raise InvalidRequestError(
                "platform.callback_timeout_seconds 必须 > 0，"
                f"收到: {self.callback_timeout_seconds!r}"
            )
        if self.callback_max_retries <= 0:
            raise InvalidRequestError(
                f"platform.callback_max_retries 必须 > 0，"
                f"收到: {self.callback_max_retries!r}"
            )
        channel_ids = [c.channel_id for c in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise InvalidRequestError("channels 中存在重复的 channel_id")


def load_config_from_file(path: str) -> PlatformConfig:
    """从 JSON 配置文件加载 PlatformConfig（供 `uvicorn platform_service.app:app`
    生产启动路径使用，示例结构见 examples/platform_config.example.json）。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    tenants = [
        TenantConfig(
            api_key=t["api_key"],
            tenant_id=t["tenant_id"],
            max_concurrent_requests=t["max_concurrent_requests"],
        )
        for t in raw["tenants"]
    ]
    price_table = PriceTable(
        prices={
            model: ModelPrice(
                input_per_1k_usd=price["input_per_1k_usd"],
                output_per_1k_usd=price["output_per_1k_usd"],
            )
            for model, price in raw["price_table"].items()
        }
    )
    channels = [
        ChannelConfig(
            channel_id=c["channel_id"],
            tenant_id=c["tenant_id"],
            callback_url=c["callback_url"],
            callback_secret=c.get("callback_secret"),
        )
        for c in raw.get("channels", [])
    ]
    return PlatformConfig(
        tenants=tenants,
        global_max_concurrent_requests=raw["global_max_concurrent_requests"],
        request_timeout_seconds=raw["request_timeout_seconds"],
        model=raw["model"],
        max_steps=raw["max_steps"],
        provider_base_url=raw["provider_base_url"],
        price_table=price_table,
        provider_api_key=raw.get("provider_api_key"),
        session_memory_db_path=raw.get("session_memory_db_path", "platform_sessions.db"),
        long_term_memory_db_path=raw.get(
            "long_term_memory_db_path", "platform_long_term.db"
        ),
        channels=channels,
        callback_timeout_seconds=raw.get("callback_timeout_seconds", 10.0),
        callback_max_retries=raw.get("callback_max_retries", 3),
    )
