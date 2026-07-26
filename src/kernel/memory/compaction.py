"""压缩判定与执行（见 specs/003 data-model.md 状态机，research.md R5/R6）。"""

from dataclasses import dataclass

from kernel.memory.models import ContextBudget
from kernel.memory.storage import StoredMessage
from kernel.provider import LLMProvider, LLMRequest, Message

SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请把以下对话历史压缩为一段简洁的第三人称摘要，"
    "保留关键事实、决定与未解决的问题，不要添加对话中没有的信息。"
)


@dataclass
class CompactionPlan:
    to_compact: list[StoredMessage]
    to_keep: list[StoredMessage]

    @property
    def needed(self) -> bool:
        return len(self.to_compact) > 0


def estimate_total_tokens(rows: list[StoredMessage]) -> int:
    """字符数/4 粗估（同 001 pricing.estimate_input_tokens 的策略与已知偏差，
    research.md R4；此处不复用该函数本身，因其签名绑定 LLMRequest 而非
    消息列表，直接复用估算策略即可）。"""
    total_chars = sum(len(r.message.content) for r in rows)
    return max(1, total_chars // 4) if rows else 0


def plan_compaction(rows: list[StoredMessage], budget: ContextBudget) -> CompactionPlan | None:
    """若累计 token 未超预算，返回 None（不压缩）；否则返回压缩计划
    （to_compact 可能为空，调用方需据此跳过，Edge Case：所有消息在保留窗口内）。
    """
    total_tokens = estimate_total_tokens(rows)
    if total_tokens <= budget.max_context_tokens:
        return None

    keep_count = min(budget.keep_recent_messages, len(rows))
    to_keep = rows[len(rows) - keep_count :] if keep_count else []
    to_compact = rows[: len(rows) - keep_count]
    return CompactionPlan(to_compact=to_compact, to_keep=to_keep)


def build_summary_request(
    to_compact: list[StoredMessage], *, tenant_id: str, model: str
) -> LLMRequest:
    transcript = "\n".join(f"{r.message.role}: {r.message.content}" for r in to_compact)
    return LLMRequest(
        tenant_id=tenant_id,
        model=model,
        messages=(
            Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
            Message(role="user", content=transcript),
        ),
    )


async def compact_if_needed(
    rows: list[StoredMessage],
    budget: ContextBudget,
    provider: LLMProvider,
    model: str,
    *,
    tenant_id: str,
) -> tuple[list[int], Message] | None:
    """返回 (待删除的 seq 列表, 摘要消息) 或 None（无需压缩）。

    调用方负责在 provider 调用成功后，于同一存储事务内执行删除+插入
    （原子替换，见 research.md R5；provider 失败时本函数直接上抛，
    调用方尚未触碰存储层，原始数据不受影响，FR-007）。
    """
    plan = plan_compaction(rows, budget)
    if plan is None or not plan.needed:
        return None

    request = build_summary_request(plan.to_compact, tenant_id=tenant_id, model=model)
    response = await provider.complete(request)
    summary_message = Message(role="system", content=response.content)
    seqs_to_remove = [r.seq for r in plan.to_compact]
    return seqs_to_remove, summary_message
