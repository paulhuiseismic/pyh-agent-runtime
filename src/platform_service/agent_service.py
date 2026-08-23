import asyncio
import logging
from datetime import datetime, timezone

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, Message
from kernel.react.engine import ReactEngine
from kernel.tool import McpServerConnection, ToolRegistry, register_mcp_tools
from platform_service.audit import AuditEntry, AuditStore
from platform_service.config import PlatformConfig
from platform_service.errors import QuotaExceededError
from platform_service.models import AgentRunRequest, AgentRunResult

logger = logging.getLogger(__name__)

# 应用启动时建立 MCP 连接不对应任何具体调用方租户，用此哨兵值归属遥测记录。
_STARTUP_TENANT_ID = "system-startup"


def _today_utc_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def build_agent_service(
    config: PlatformConfig, *, provider: LLMProvider | None = None
) -> "AgentService":
    """按 PlatformConfig 组合出一次可用的 AgentService（research.md R4）。

    provider 参数供测试注入 stub LLMProvider；生产环境（未提供时）按
    config.provider_base_url/provider_api_key/price_table/provider_call_limits
    构造真实 LLMProvider（FR-013/FR-014）。
    """
    if provider is None:
        provider = LLMProvider(
            base_url=config.provider_base_url,
            api_key=config.provider_api_key,
            price_table=config.price_table,
            default_limits=config.provider_call_limits,
        )

    tool_registry = ToolRegistry()
    for mcp_config in config.mcp_servers:
        connection = McpServerConnection(mcp_config)
        await connection.connect(tenant_id=_STARTUP_TENANT_ID)
        await register_mcp_tools(connection, tool_registry)

    session_memory = SqliteMemory(
        db_path=config.session_memory_db_path, provider=provider, model=config.model
    )
    long_term_memory = LongTermMemory(
        db_path=config.long_term_memory_db_path, provider=provider, model=config.model
    )
    audit_store = AuditStore(config.audit_db_path)

    return AgentService(
        provider=provider,
        tool_registry=tool_registry,
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
        audit_store=audit_store,
    )


class SessionLockRegistry:
    """按 session_id 惰性创建/复用 asyncio.Lock（FR-015，data-model.md）。

    不同 session_id 互不阻塞；未提供 session_id 的调用不经过此注册表。
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


class QuotaLockRegistry:
    """按 tenant_id 惰性创建/复用 asyncio.Lock（010 配额检查的并发一致性，
    research.md R6）。与 SessionLockRegistry 完全同写法，只是键换成
    tenant_id；未配置配额的租户不经过此注册表，零开销。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, tenant_id: str) -> asyncio.Lock:
        lock = self._locks.get(tenant_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[tenant_id] = lock
        return lock


class _UsageTrackingProvider:
    """委托包装 LLMProvider，累加本次调用（可能触发多次 complete()）的
    总用量/成本（research.md R1）。仅存活于单次 handle() 调用期间，
    不修改 LLMProvider/ReactEngine 任何冻结接口。"""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    async def complete(self, request):
        response = await self._provider.complete(request)
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens
        self.total_cost_usd += response.cost_usd
        return response


class AgentService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        session_memory: SqliteMemory,
        long_term_memory: LongTermMemory,
        config: PlatformConfig,
        audit_store: AuditStore | None = None,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._session_memory = session_memory
        self._long_term_memory = long_term_memory
        self._config = config
        self._audit_store = audit_store
        self._session_locks = SessionLockRegistry()
        self._quota_locks = QuotaLockRegistry()

    @property
    def audit_store(self) -> AuditStore | None:
        return self._audit_store

    def _quota_for_tenant(self, tenant_id: str) -> float | None:
        for tenant in self._config.tenants:
            if tenant.tenant_id == tenant_id:
                return tenant.daily_cost_quota_usd
        return None

    async def handle(
        self, request: AgentRunRequest, *, tenant_id: str, source: str = "unknown"
    ) -> AgentRunResult:
        quota = self._quota_for_tenant(tenant_id)
        if self._audit_store is not None and quota is not None:
            lock = self._quota_locks.get_lock(tenant_id)
            async with lock:
                return await self._handle_with_session_lock(
                    request, tenant_id=tenant_id, source=source
                )
        return await self._handle_with_session_lock(
            request, tenant_id=tenant_id, source=source
        )

    async def _handle_with_session_lock(
        self, request: AgentRunRequest, *, tenant_id: str, source: str
    ) -> AgentRunResult:
        if request.session_id is not None:
            lock = self._session_locks.get_lock(request.session_id)
            async with lock:
                return await self._handle_locked(request, tenant_id=tenant_id, source=source)
        return await self._handle_locked(request, tenant_id=tenant_id, source=source)

    async def _handle_locked(
        self, request: AgentRunRequest, *, tenant_id: str, source: str = "unknown"
    ) -> AgentRunResult:
        quota = self._quota_for_tenant(tenant_id)
        if self._audit_store is not None and quota is not None:
            current_cost = await self._audit_store.sum_cost_since(
                tenant_id, _today_utc_start()
            )
            if current_cost >= quota:
                raise QuotaExceededError(tenant_id, quota)

        history: list[Message] = []
        if request.session_id is not None:
            history = await self._session_memory.load(request.session_id, tenant_id=tenant_id)

        long_term_facts = await self._long_term_memory.query(tenant_id=tenant_id)

        goal_parts = []
        if long_term_facts:
            facts_text = "\n".join(f"- {entry.content}" for entry in long_term_facts)
            goal_parts.append(f"已知的用户相关事实：\n{facts_text}")
        if history:
            history_text = "\n".join(f"{m.role}: {m.content}" for m in history)
            goal_parts.append(f"此前的对话历史：\n{history_text}")
        goal_parts.append(request.goal)
        combined_goal = "\n\n".join(goal_parts)

        usage_tracker = _UsageTrackingProvider(self._provider)
        engine = ReactEngine(
            provider=usage_tracker,
            tools=self._tool_registry.as_dict(),
            model=self._config.model,
        )
        try:
            answer = await engine.run(
                combined_goal, tenant_id=tenant_id, max_steps=self._config.max_steps
            )
        except Exception:
            await self._record_audit_best_effort(
                tenant_id=tenant_id, source=source, usage_tracker=usage_tracker, status="failure"
            )
            raise

        if request.session_id is not None:
            await self._session_memory.append(
                request.session_id, Message(role="user", content=request.goal), tenant_id=tenant_id
            )
            await self._session_memory.append(
                request.session_id,
                Message(role="assistant", content=answer),
                tenant_id=tenant_id,
            )
            try:
                updated_history = await self._session_memory.load(
                    request.session_id, tenant_id=tenant_id
                )
                await self._long_term_memory.extract(tuple(updated_history), tenant_id=tenant_id)
            except Exception:
                logger.warning(
                    "long-term memory extraction failed, request result unaffected",
                    exc_info=True,
                )

        await self._record_audit_best_effort(
            tenant_id=tenant_id, source=source, usage_tracker=usage_tracker, status="success"
        )

        return AgentRunResult(status="success", answer=answer, session_id=request.session_id)

    async def _record_audit_best_effort(
        self, *, tenant_id: str, source: str, usage_tracker: _UsageTrackingProvider, status: str
    ) -> None:
        if self._audit_store is None:
            return
        try:
            await self._audit_store.record(
                AuditEntry(
                    tenant_id=tenant_id,
                    source=source,
                    timestamp=datetime.now(timezone.utc),
                    input_tokens=usage_tracker.total_input_tokens,
                    output_tokens=usage_tracker.total_output_tokens,
                    cost_usd=usage_tracker.total_cost_usd,
                    status=status,
                )
            )
        except Exception:
            logger.warning("audit record write failed, request result unaffected", exc_info=True)
