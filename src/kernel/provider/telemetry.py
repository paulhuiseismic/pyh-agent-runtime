"""GenAI 语义约定 span 发出（FR-006/FR-007，属性契约见 specs/001 data-model.md）。

遥测失败绝不影响调用本身（宪法原则 V + FR-007）：所有 OTel 操作包裹在
try/except 中，异常仅记 warning 日志。
"""

import logging
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)

_tracer = trace.get_tracer("kernel.provider")

MISSING_TENANT = "<missing>"


@contextmanager
def llm_call_span(*, tenant_id: str | None, model: str):
    """包裹一次 LLM 调用的 span 上下文。

    yield 一个 recorder（成功时调用 record_success 补充用量属性）；
    调用方异常自动标记 span status=ERROR 并原样上抛。
    """
    span = None
    try:
        span = _tracer.start_span(f"chat {model}")
        span.set_attribute("tenant_id", tenant_id or MISSING_TENANT)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
    except Exception:
        logger.warning("遥测 span 创建失败，调用继续", exc_info=True)

    recorder = _SpanRecorder(span)
    try:
        yield recorder
    except Exception as exc:
        _safe(lambda: span.set_status(Status(StatusCode.ERROR, type(exc).__name__)))
        _safe(lambda: span.set_attribute("error.type", type(exc).__name__))
        raise
    else:
        _safe(lambda: span.set_status(Status(StatusCode.OK)))
    finally:
        _safe(lambda: span.end())


class _SpanRecorder:
    def __init__(self, span):
        self._span = span

    def record_success(self, *, response_model: str, input_tokens: int,
                       output_tokens: int, cost_usd: float) -> None:
        def _record():
            self._span.set_attribute("gen_ai.response.model", response_model)
            self._span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            self._span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            self._span.set_attribute("gen_ai.usage.cost", cost_usd)

        _safe(_record)


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        logger.warning("遥测操作失败，调用继续", exc_info=True)
