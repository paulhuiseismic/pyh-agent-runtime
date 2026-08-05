import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from platform_service.agent_service import AgentService, build_agent_service
from platform_service.auth import resolve_tenant
from platform_service.config import PlatformConfig, load_config_from_file
from platform_service.errors import (
    AuthenticationError,
    ConcurrencyLimitExceededError,
    RequestTimeoutError,
)
from platform_service.models import AgentRunRequest, AgentRunResult
from platform_service.scheduler import ConcurrencyScheduler


def create_app(
    config: PlatformConfig, *, agent_service: AgentService | None = None
) -> FastAPI:
    """构建平台 REST 应用。

    agent_service 由调用方（测试）预先构建时直接使用（同步注入，便于用 stub
    provider 驱动）；未提供时通过 FastAPI lifespan 在应用启动阶段按 config
    构建一次（生产路径，research.md R4）。
    """
    lifespan = None
    if agent_service is None:

        @asynccontextmanager
        async def _lifespan(app: FastAPI):
            app.state.agent_service = await build_agent_service(config)
            yield

        lifespan = _lifespan

    app = FastAPI(lifespan=lifespan)
    app.state.config = config
    app.state.agent_service = agent_service
    app.state.scheduler = ConcurrencyScheduler(config)

    @app.post("/v1/agent/run", response_model=AgentRunResult)
    async def run_agent(
        request: AgentRunRequest, x_api_key: str | None = Header(default=None)
    ) -> AgentRunResult:
        try:
            tenant_id = resolve_tenant(x_api_key, config)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        scheduler: ConcurrencyScheduler = app.state.scheduler
        try:
            await scheduler.try_acquire(tenant_id)
        except ConcurrencyLimitExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

        try:
            service: AgentService = app.state.agent_service
            try:
                return await asyncio.wait_for(
                    service.handle(request, tenant_id=tenant_id),
                    timeout=config.request_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=504,
                    detail=str(RequestTimeoutError(config.request_timeout_seconds)),
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"kernel processing failed: {exc}"
                ) from exc
        finally:
            scheduler.release(tenant_id)

    return app


# `uvicorn platform_service.app:app` 生产启动入口：从 PLATFORM_SERVICE_CONFIG
# 环境变量指定的 JSON 文件加载配置（示例见
# examples/platform_config.example.json，quickstart.md 第 2 节）。
_config_path = os.environ.get("PLATFORM_SERVICE_CONFIG")
app = create_app(load_config_from_file(_config_path)) if _config_path else None
