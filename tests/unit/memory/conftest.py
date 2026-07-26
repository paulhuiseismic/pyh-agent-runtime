"""memory 测试公共设施：临时 SQLite 文件 + 脚本化 stub provider（见 specs/003 research.md R8）。"""

import json
import tempfile
from pathlib import Path

import httpx
import pytest

from kernel.provider import LLMProvider, ModelPrice, PriceTable

MODEL = "memory-test-model"


@pytest.fixture
def price_table() -> PriceTable:
    return PriceTable(prices={MODEL: ModelPrice(input_per_1k_usd=0.01, output_per_1k_usd=0.03)})


@pytest.fixture
def db_path():
    """真实临时 SQLite 文件路径（不用 :memory:，以验证重启后可读，research.md R8）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "memory.db")


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def scripted_summary_provider(price_table: PriceTable, summaries: list[str]) -> LLMProvider:
    """按调用顺序依次返回 summaries 中的摘要文本；超出序列长度则报错。"""
    queue = list(summaries)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError("stub provider 摘要序列已耗尽，压缩调用次数超出预期")
        content = queue.pop(0)
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler)
    )


def erroring_provider(exc: Exception) -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )
