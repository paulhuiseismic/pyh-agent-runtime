import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

from platform_service.audit import UsageSummary

from platform_service.agent_service import AgentService, build_agent_service
from platform_service.auth import resolve_tenant
from platform_service.config import PlatformConfig, load_config_from_file
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
from platform_service.scheduler import ConcurrencyScheduler
from platform_service.telemetry import platform_request_span


def create_app(
    config: PlatformConfig,
    *,
    agent_service: AgentService | None = None,
    message_gateway: MessageGateway | None = None,
) -> FastAPI:
    """构建平台 REST 应用。

    agent_service/message_gateway 由调用方（测试）预先构建时直接使用
    （同步注入，便于用 stub provider/回调记录器驱动）；未提供时通过
    FastAPI lifespan 在应用启动阶段按 config 构建一次（生产路径，
    research.md R4；009 message_gateway 同一 lifespan 内构建）。
    """
    lifespan = None
    if agent_service is None:

        @asynccontextmanager
        async def _lifespan(app: FastAPI):
            app.state.agent_service = await build_agent_service(config)
            app.state.message_gateway = await build_message_gateway(
                config, agent_service=app.state.agent_service
            )
            yield

        lifespan = _lifespan

    app = FastAPI(lifespan=lifespan)
    app.state.config = config
    app.state.agent_service = agent_service
    app.state.message_gateway = message_gateway
    app.state.scheduler = ConcurrencyScheduler(config)

    @app.post("/v1/agent/run", response_model=AgentRunResult)
    async def run_agent(
        request: AgentRunRequest, x_api_key: str | None = Header(default=None)
    ) -> AgentRunResult:
        try:
            tenant_id = resolve_tenant(x_api_key, config)
        except AuthenticationError as exc:
            # 鉴权失败发生在 platform.request span 开始之前（未识别出租户前
            # 不产生任何内核/平台可观测记录，data-model.md）。
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        with platform_request_span(
            tenant_id=tenant_id, session_id=request.session_id
        ) as span:
            scheduler: ConcurrencyScheduler = app.state.scheduler
            try:
                await scheduler.try_acquire(tenant_id)
            except ConcurrencyLimitExceededError as exc:
                span.set_result("concurrency_exceeded")
                raise HTTPException(status_code=429, detail=str(exc)) from exc

            try:
                service: AgentService = app.state.agent_service
                try:
                    result = await asyncio.wait_for(
                        service.handle(request, tenant_id=tenant_id, source="rest"),
                        timeout=config.request_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    span.set_result("timeout")
                    raise HTTPException(
                        status_code=504,
                        detail=str(RequestTimeoutError(config.request_timeout_seconds)),
                    ) from exc
                except QuotaExceededError as exc:
                    span.set_result("quota_exceeded")
                    raise HTTPException(status_code=402, detail=str(exc)) from exc
                except Exception as exc:
                    span.set_result("kernel_error")
                    raise HTTPException(
                        status_code=502, detail=f"kernel processing failed: {exc}"
                    ) from exc
                span.set_result("success")
                return result
            finally:
                scheduler.release(tenant_id)

    @app.post(
        "/v1/messages/inbound", response_model=InboundAcceptResult, status_code=202
    )
    async def receive_message(message: InboundMessage) -> InboundAcceptResult:
        gateway: MessageGateway = app.state.message_gateway
        try:
            return await gateway.handle_inbound(message)
        except ChannelNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/audit/usage", response_model=UsageSummary)
    async def get_usage(
        start: datetime | None = None,
        end: datetime | None = None,
        x_api_key: str | None = Header(default=None),
    ) -> UsageSummary:
        try:
            tenant_id = resolve_tenant(x_api_key, config)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        now = datetime.now(timezone.utc)
        range_start = start or now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = end or now

        service: AgentService = app.state.agent_service
        return await service.audit_store.query_usage(tenant_id, range_start, range_end)

    return app


# `uvicorn platform_service.app:app` 生产启动入口：从 PLATFORM_SERVICE_CONFIG
# 环境变量指定的 JSON 文件加载配置（示例见
# examples/platform_config.example.json，quickstart.md 第 2 节）。
_config_path = os.environ.get("PLATFORM_SERVICE_CONFIG")
app = create_app(load_config_from_file(_config_path)) if _config_path else None
