"""T020 [US3]: CPU/内存超限（仅 POSIX，Windows 跳过并注明原因）。"""

import sys

import pytest

from kernel.tool import SandboxedTool, SandboxLimits, SandboxResourceExceededError

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="资源限制（RLIMIT_AS/RLIMIT_CPU）仅 POSIX 硬性生效，见 research.md R2",
)


async def test_memory_limit_exceeded_raises_resource_exceeded(grow_memory_command):
    limits = SandboxLimits(max_memory_bytes=64 * 1024 * 1024, timeout_seconds=10.0)
    tool = SandboxedTool(
        name="grow", description="grows memory", command=grow_memory_command, limits=limits
    )
    with pytest.raises(SandboxResourceExceededError) as exc_info:
        await tool.invoke({}, tenant_id="tenant-a")
    assert exc_info.value.resource_name == "memory"
    assert exc_info.value.limit == limits.max_memory_bytes
