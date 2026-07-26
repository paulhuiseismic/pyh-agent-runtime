"""LongTermMemory：跨会话长期记忆编排（提炼+查询，见 specs/004 data-model.md 状态机）。"""

from kernel.memory.extraction import build_extraction_request, parse_extraction
from kernel.memory.long_term_models import ExtractionResult, MemoryEntry
from kernel.memory.long_term_storage import LongTermStore
from kernel.memory.telemetry import long_term_memory_span
from kernel.provider import LLMProvider, Message
from kernel.provider.errors import InvalidRequestError


class LongTermMemory:
    def __init__(self, *, db_path: str, provider: LLMProvider, model: str) -> None:
        self._store = LongTermStore(db_path)
        self._provider = provider
        self._model = model

    async def aclose(self) -> None:
        await self._store.close()

    async def extract(
        self, history: tuple[Message, ...], *, tenant_id: str
    ) -> ExtractionResult:
        # provider 调用需在 span 内发起，使 chat span 成为其子 span（同 002/003 模式）
        with long_term_memory_span("extract", tenant_id=tenant_id):
            if not history:
                return ExtractionResult(entries=[])

            request = build_extraction_request(history, tenant_id=tenant_id, model=self._model)
            # provider 异常（超时/超限等）原样上抛，长期记忆库不受影响（FR-005）：
            # 本次尚未触碰存储层，异常发生在写入之前
            response = await self._provider.complete(request)
            result = parse_extraction(response.content)

            if result.entries:
                await self._store.upsert_entries(tenant_id, result.entries)
            return result

    async def query(self, *, tenant_id: str, limit: int = 10) -> list[MemoryEntry]:
        with long_term_memory_span("query", tenant_id=tenant_id):
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise InvalidRequestError(f"limit 必须是正整数，收到: {limit!r}")
            return await self._store.query_entries(tenant_id, limit)
