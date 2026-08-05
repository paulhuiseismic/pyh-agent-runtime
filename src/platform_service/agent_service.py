import asyncio
import logging

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, Message
from kernel.react.engine import ReactEngine
from kernel.tool import McpServerConnection, ToolRegistry, register_mcp_tools
from platform_service.config import PlatformConfig
from platform_service.models import AgentRunRequest, AgentRunResult

logger = logging.getLogger(__name__)

# 应用启动时建立 MCP 连接不对应任何具体调用方租户，用此哨兵值归属遥测记录。
_STARTUP_TENANT_ID = "system-startup"


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

    return AgentService(
        provider=provider,
        tool_registry=tool_registry,
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
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


class AgentService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        session_memory: SqliteMemory,
        long_term_memory: LongTermMemory,
        config: PlatformConfig,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._session_memory = session_memory
        self._long_term_memory = long_term_memory
        self._config = config
        self._session_locks = SessionLockRegistry()

    async def handle(self, request: AgentRunRequest, *, tenant_id: str) -> AgentRunResult:
        if request.session_id is not None:
            lock = self._session_locks.get_lock(request.session_id)
            async with lock:
                return await self._handle_locked(request, tenant_id=tenant_id)
        return await self._handle_locked(request, tenant_id=tenant_id)

    async def _handle_locked(
        self, request: AgentRunRequest, *, tenant_id: str
    ) -> AgentRunResult:
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

        engine = ReactEngine(
            provider=self._provider,
            tools=self._tool_registry.as_dict(),
            model=self._config.model,
        )
        answer = await engine.run(
            combined_goal, tenant_id=tenant_id, max_steps=self._config.max_steps
        )

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

        return AgentRunResult(status="success", answer=answer, session_id=request.session_id)
