"""memory 操作遥测：memory.{operation} span（见 specs/003 data-model.md，research.md R7）。"""

import logging
from contextlib import contextmanager

from opentelemetry.trace import Status, StatusCode

from kernel.provider.telemetry import _tracer

logger = logging.getLogger(__name__)


class _MemorySpanHandle:
    def __init__(self, span):
        self._span = span

    def set_compaction_triggered(self, triggered: bool) -> None:
        _safe(lambda: self._span.set_attribute("memory.compaction_triggered", triggered))


@contextmanager
def memory_operation_span(operation: str, *, session_id: str, tenant_id: str):
    try:
        span_cm = _tracer.start_as_current_span(f"memory.{operation}")
        span = span_cm.__enter__()
        span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("session_id", session_id)
    except Exception:
        logger.warning("memory.%s span 创建失败，操作继续", operation, exc_info=True)
        span_cm, span = None, None

    try:
        yield _MemorySpanHandle(span)
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
