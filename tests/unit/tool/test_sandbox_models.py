"""T009: SandboxLimits 与异常层级单元测试。"""

import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.tool.sandbox_models import (
    DEFAULT_MAX_CPU_SECONDS,
    DEFAULT_MAX_MEMORY_BYTES,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    SandboxLimits,
    SandboxResourceExceededError,
    SandboxStartupError,
    SandboxTimeoutError,
    SandboxToolExecutionError,
)


class TestSandboxLimits:
    def test_default_values(self):
        limits = SandboxLimits()
        assert limits.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert limits.max_cpu_seconds == DEFAULT_MAX_CPU_SECONDS
        assert limits.max_memory_bytes == DEFAULT_MAX_MEMORY_BYTES
        assert limits.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES

    @pytest.mark.parametrize("field,value", [
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
        ("max_cpu_seconds", 0),
        ("max_memory_bytes", -100),
        ("max_output_bytes", 0),
    ])
    def test_non_positive_fields_rejected(self, field, value):
        with pytest.raises(InvalidRequestError):
            SandboxLimits(**{field: value})


class TestExceptionHierarchy:
    def test_timeout_error_fields(self):
        err = SandboxTimeoutError(timeout_seconds=5.0)
        assert err.timeout_seconds == 5.0

    def test_resource_exceeded_error_fields(self):
        err = SandboxResourceExceededError(resource_name="memory", limit=1024)
        assert err.resource_name == "memory"
        assert err.limit == 1024

    def test_startup_error_fields(self):
        err = SandboxStartupError(detail="command not found")
        assert err.detail == "command not found"

    def test_tool_execution_error_fields(self):
        err = SandboxToolExecutionError(exit_code=1, stderr_snippet="boom")
        assert err.exit_code == 1
        assert err.stderr_snippet == "boom"
