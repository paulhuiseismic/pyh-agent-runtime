"""步骤遥测：react.step span（见 specs/002 data-model.md 与 research.md R5）。

复用 kernel.provider 已有的 tracer（同一 tracer name），使该步内的
provider 调用 span 天然成为 react.step span 的子 span（OTel context 传播，
需在 react_step_span 的 with 块内发起 provider 调用）。
遥测失败不影响运行（FR-009，沿用 001 telemetry 容错模式）。
"""

import logging
from contextlib import contextmanager

from opentelemetry.trace import Status, StatusCode

from kernel.provider.telemetry import _tracer

logger = logging.getLogger(__name__)


@contextmanager
def react_step_span(step_index: int, action: str, tool_name: str | None = None):
    try:
        span_cm = _tracer.start_as_current_span("react.step")
        span = span_cm.__enter__()
        span.set_attribute("react.step.index", step_index)
        span.set_attribute("react.step.action", action)
        if tool_name:
            span.set_attribute("react.step.tool_name", tool_name)
    except Exception:
        logger.warning("react.step span 创建失败，运行继续", exc_info=True)
        span_cm, span = None, None

    try:
        yield
    except Exception as exc:
        _safe(lambda: span.set_status(Status(StatusCode.ERROR, type(exc).__name__)))
        _safe(lambda: span.set_attribute("error.type", type(exc).__name__))
        raise
    else:
        _safe(lambda: span.set_status(Status(StatusCode.OK)))
    finally:
        if span_cm is not None:
            _safe(lambda: span_cm.__exit__(None, None, None))


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        logger.warning("遥测操作失败，调用继续", exc_info=True)
