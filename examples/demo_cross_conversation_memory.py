"""跨对话记忆 demo：组合 001（provider）+ 003（会话记忆）+ 004（长期记忆），
用真实 LiteLLM proxy 演示"第一次对话中说的偏好，第二次全新对话里被记住"。

流程:
  1. 对话 1（session_id="conv-1"）：用户表达一个偏好，LLM 回应，
     整轮对话存入 003 的 SqliteMemory（会话历史）。
  2. 对话结束时，把这段历史交给 004 的 LongTermMemory.extract()，
     提炼出偏好并写入该租户的长期记忆库。
  3. 对话 2（session_id="conv-2"，全新会话）：开始前先查询长期记忆，
     把提炼出的偏好注入到新对话的 system 提示中，再提问一个新问题，
     观察 LLM 的回答是否体现出对该偏好的了解。

前置条件: 本地运行 LiteLLM proxy（见 examples/README.md），配置与
demo_react_weather.py / demo_proxy.py 相同。

环境变量:
  LITELLM_BASE_URL  默认 http://localhost:4000
  LITELLM_API_KEY   可选
  MEMORY_MODEL      默认 azure-gpt4o-mini（须与 litellm-config.yaml 的 model_name 一致）

运行: python examples/demo_cross_conversation_memory.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.memory import LongTermMemory, SqliteMemory
from kernel.provider import LLMProvider, LLMRequest, Message, ModelPrice, PriceTable

TENANT_ID = "tenant-cross-conv-demo"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


async def ask_llm(provider: LLMProvider, model: str, messages: tuple[Message, ...]) -> str:
    response = await provider.complete(
        LLMRequest(tenant_id=TENANT_ID, model=model, messages=messages)
    )
    return response.content


async def main() -> None:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
    api_key = os.environ.get("LITELLM_API_KEY")
    model = os.environ.get("MEMORY_MODEL", "azure-gpt4o-mini")

    setup_console_tracing()

    provider = LLMProvider(
        base_url=base_url,
        api_key=api_key,
        # 演示用单价，请按你实际部署的模型调整
        price_table=PriceTable(prices={model: ModelPrice(0.15, 0.6)}),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "cross_conv_demo.db")
        session_memory = SqliteMemory(db_path=db_path, provider=provider, model=model)
        long_term_memory = LongTermMemory(db_path=db_path, provider=provider, model=model)

        print("=== 对话 1（session=conv-1）===")
        user_msg_1 = Message(role="user", content="我更喜欢简洁的回答，不要长篇大论，一两句话说清楚就行。")
        await session_memory.append("conv-1", user_msg_1, tenant_id=TENANT_ID)
        reply_1 = await ask_llm(provider, model, (user_msg_1,))
        print(f"用户: {user_msg_1.content}")
        print(f"助手: {reply_1}\n")
        await session_memory.append(
            "conv-1", Message(role="assistant", content=reply_1), tenant_id=TENANT_ID
        )

        print("=== 对话 1 结束，提炼长期记忆 ===")
        history = tuple(await session_memory.load("conv-1", tenant_id=TENANT_ID))
        extraction = await long_term_memory.extract(history, tenant_id=TENANT_ID)
        print(f"提炼出的记忆条目: {[(e.category, e.content) for e in extraction.entries]}\n")

        print("=== 对话 2（session=conv-2，全新会话）===")
        remembered = await long_term_memory.query(tenant_id=TENANT_ID)
        if remembered:
            preference_note = "；".join(e.content for e in remembered)
            system_msg = Message(
                role="system",
                content=f"你已知的该用户偏好: {preference_note}。请在回答时遵循这些偏好。",
            )
        else:
            system_msg = Message(role="system", content="你是一个助手。")

        user_msg_2 = Message(role="user", content="帮我解释一下什么是光合作用。")
        await session_memory.append("conv-2", user_msg_2, tenant_id=TENANT_ID)
        reply_2 = await ask_llm(provider, model, (system_msg, user_msg_2))
        print(f"注入的偏好: {system_msg.content}")
        print(f"用户: {user_msg_2.content}")
        print(f"助手: {reply_2}\n")

        await session_memory.aclose()
        await long_term_memory.aclose()

    await provider.aclose()
    print("演示完成：对话 2 从未提及'喜欢简洁回答'，但因长期记忆的注入，"
          "回答风格应体现出该偏好。")


if __name__ == "__main__":
    asyncio.run(main())
