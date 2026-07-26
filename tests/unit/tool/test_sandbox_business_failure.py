"""T016 [US2]: 非零退出码业务失败、启动失败（命令不存在）。"""

import pytest

from kernel.tool import SandboxedTool, SandboxStartupError, SandboxToolExecutionError


async def test_nonzero_exit_raises_tool_execution_error(exit_nonzero_command):
    tool = SandboxedTool(name="fail", description="fails", command=exit_nonzero_command)
    with pytest.raises(SandboxToolExecutionError) as exc_info:
        await tool.invoke({}, tenant_id="tenant-a")
    assert exc_info.value.exit_code == 1
    assert "intentional failure" in exc_info.value.stderr_snippet


async def test_nonexistent_command_raises_startup_error():
    tool = SandboxedTool(
        name="broken", description="broken", command=["/path/does/not/exist/binary"]
    )
    with pytest.raises(SandboxStartupError):
        await tool.invoke({}, tenant_id="tenant-a")
