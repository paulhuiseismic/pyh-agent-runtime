"""思考阶段的提示构造与结构化输出解析（见 specs/002 research.md R1）。"""

import json

from kernel.provider.models import Message
from kernel.react.models import Observation

SYSTEM_PROMPT_TEMPLATE = """你是一个通过工具解决目标的助手。可用工具：
{tools_desc}

每一步你必须严格输出以下两种 JSON 之一，不要输出任何其他文字：
1. 给出最终答案：{{"action": "final_answer", "content": "<答案文本>"}}
2. 调用工具：{{"action": "call_tool", "tool": "<工具名>", "arguments": {{...}}}}
"""


def build_thought_messages(
    goal: str, tool_descriptions: dict[str, str], history: list[tuple[str, Observation]]
) -> tuple[Message, ...]:
    """构造含工具清单与历史步骤的消息列表。

    history: 已发生的 (action_summary, observation) 序列，action_summary 为
    该步决策的简要描述（如 "call_tool: search"），用于让模型看到之前尝试与结果。
    """
    tools_desc = "\n".join(f"- {name}: {desc}" for name, desc in tool_descriptions.items()) or "（无可用工具）"
    system = Message(
        role="system", content=SYSTEM_PROMPT_TEMPLATE.format(tools_desc=tools_desc)
    )
    messages = [system, Message(role="user", content=f"目标: {goal}")]
    for action_summary, observation in history:
        messages.append(Message(role="assistant", content=action_summary))
        prefix = "观察（成功）" if observation.success else "观察（失败）"
        messages.append(Message(role="user", content=f"{prefix}: {observation.content}"))
    return tuple(messages)


class ThoughtDecision:
    """思考结果解析后的决策，action 为 final_answer / call_tool / malformed 之一。"""

    __slots__ = ("action", "content", "tool", "arguments", "raw")

    def __init__(
        self,
        action: str,
        *,
        content: str = "",
        tool: str = "",
        arguments: dict | None = None,
        raw: str = "",
    ):
        self.action = action
        self.content = content
        self.tool = tool
        self.arguments = arguments or {}
        self.raw = raw


def parse_thought(content: str) -> ThoughtDecision:
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return ThoughtDecision("malformed", raw=content[:200])

    if not isinstance(data, dict):
        return ThoughtDecision("malformed", raw=content[:200])

    action = data.get("action")
    if action == "final_answer":
        answer = data.get("content")
        if not isinstance(answer, str):
            return ThoughtDecision("malformed", raw=content[:200])
        return ThoughtDecision("final_answer", content=answer, raw=content[:200])

    if action == "call_tool":
        tool = data.get("tool")
        arguments = data.get("arguments", {})
        if not isinstance(tool, str) or not tool or not isinstance(arguments, dict):
            return ThoughtDecision("malformed", raw=content[:200])
        return ThoughtDecision("call_tool", tool=tool, arguments=arguments, raw=content[:200])

    return ThoughtDecision("malformed", raw=content[:200])
