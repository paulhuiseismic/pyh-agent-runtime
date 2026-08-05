"""platform.request span（见 specs/007 data-model.md 遥测 span 契约）。"""

import logging
from contextlib import contextmanager

from opentelemetry.trace import Status, StatusCode

from kernel.provider.telemetry import _tracer

logger = logging.getLogger(__name__)


class _PlatformRequestSpanHandle:
    def __init__(self, span):
        self._span = span

    def set_result(self, result: str) -> None:
        _safe(lambda: self._span.set_attribute("result", result))


@contextmanager
def platform_request_span(*, tenant_id: str, session_id: str | None):
    try:
        span_cm = _tracer.start_as_current_span("platform.request")
        span = span_cm.__enter__()
        span.set_attribute("tenant_id", tenant_id)
        if session_id is not None:
            span.set_attribute("session_id", session_id)
    except Exception:
        logger.warning("platform.request span 创建失败，调用继续", exc_info=True)
        span_cm, span = None, None

    try:
        yield _PlatformRequestSpanHandle(span)
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
