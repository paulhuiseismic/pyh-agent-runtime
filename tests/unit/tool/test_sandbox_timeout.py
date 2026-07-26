"""T019/T021 [US3]: 超时强制终止（所有平台）、安全默认值。"""

import time

import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.tool import SandboxedTool, SandboxLimits, SandboxTimeoutError


async def test_timeout_terminates_within_1_5x_and_raises(
    sleep_forever_command, short_timeout_limits
):
    tool = SandboxedTool(
        name="slow", description="slow tool", command=sleep_forever_command,
        limits=short_timeout_limits,
    )
    start = time.monotonic()
    with pytest.raises(SandboxTimeoutError) as exc_info:
        await tool.invoke({}, tenant_id="tenant-a")
    elapsed = time.monotonic() - start

    assert elapsed < short_timeout_limits.timeout_seconds * 1.5 + 1.0  # 留出进程启动开销余量
    assert exc_info.value.timeout_seconds == short_timeout_limits.timeout_seconds


async def test_default_limits_have_no_unlimited_option(echo_args_command):
    tool = SandboxedTool(name="echo", description="echo", command=echo_args_command)
    # 未显式提供 limits 时采用 SandboxLimits() 默认值，全部字段已在
    # test_sandbox_models.py 中验证过为正数、不允许配置为 0/负数
    assert tool._limits.timeout_seconds > 0
    assert tool._limits.max_cpu_seconds > 0
    assert tool._limits.max_memory_bytes > 0
    assert tool._limits.max_output_bytes > 0

    with pytest.raises(InvalidRequestError):
        SandboxLimits(timeout_seconds=0)
