"""提炼提示构造与结构化输出解析（见 specs/004 research.md R1/R2）。"""

import json

from kernel.memory.long_term_models import ExtractionResult, MemoryEntry
from kernel.provider import LLMRequest, Message

EXTRACTION_SYSTEM_PROMPT = (
    "你是一个记忆提炼助手。请阅读以下对话历史，找出其中值得长期记住的用户偏好或事实"
    "（不包括临时性的、与本次对话强相关的内容）。\n"
    "严格输出一个 JSON 数组，每个元素为 "
    '{"category": "<类别，如果无法判定则为 null>", "content": "<记忆内容文本>"}。\n'
    "如果没有任何值得记住的内容，输出空数组 []。不要输出数组以外的任何文字。"
)


def build_extraction_request(
    history: tuple[Message, ...], *, tenant_id: str, model: str
) -> LLMRequest:
    transcript = "\n".join(f"{m.role}: {m.content}" for m in history)
    return LLMRequest(
        tenant_id=tenant_id,
        model=model,
        messages=(
            Message(role="system", content=EXTRACTION_SYSTEM_PROMPT),
            Message(role="user", content=transcript),
        ),
    )


def _normalize_category(category) -> str | None:
    # 空字符串/全空白归一化为 None（无法判定类别），避免作为"真实类别值"
    # 参与 UNIQUE(tenant_id, category) 约束（data-model.md）
    if not isinstance(category, str):
        return None
    stripped = category.strip()
    return stripped if stripped else None


def parse_extraction(content: str) -> ExtractionResult:
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return ExtractionResult(entries=[])

    if not isinstance(data, list):
        return ExtractionResult(entries=[])

    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        item_content = item.get("content")
        if not isinstance(item_content, str) or not item_content.strip():
            continue
        entries.append(
            MemoryEntry(content=item_content, category=_normalize_category(item.get("category")))
        )
    return ExtractionResult(entries=entries)
