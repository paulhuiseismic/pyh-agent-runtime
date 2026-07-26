"""tool 执行遥测：tool.invoke span（见 specs/005 data-model.md，research.md R7）。"""

import logging
import time
from contextlib import contextmanager

from opentelemetry.trace import Status, StatusCode

from kernel.provider.telemetry import _tracer

logger = logging.getLogger(__name__)


class _ToolSpanHandle:
    def __init__(self, span):
        self._span = span

    def set_result_type(self, result_type: str) -> None:
        _safe(lambda: self._span.set_attribute("result_type", result_type))


@contextmanager
def tool_invoke_span(*, tenant_id: str, tool_name: str):
    start = time.monotonic()
    try:
        span_cm = _tracer.start_as_current_span("tool.invoke")
        span = span_cm.__enter__()
        span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("tool_name", tool_name)
    except Exception:
        logger.warning("tool.invoke span 创建失败，调用继续", exc_info=True)
        span_cm, span = None, None

    try:
        yield _ToolSpanHandle(span)
    except Exception as exc:
        _safe(lambda: span.set_status(Status(StatusCode.ERROR, type(exc).__name__)))
        _safe(lambda: span.set_attribute("error.type", type(exc).__name__))
        raise
    else:
        _safe(lambda: span.set_status(Status(StatusCode.OK)))
    finally:
        duration = time.monotonic() - start
        _safe(lambda: span.set_attribute("duration_seconds", duration))
        if span_cm is not None:
            _safe(lambda: span_cm.__exit__(None, None, None))


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        logger.warning("遥测操作失败，调用继续", exc_info=True)
