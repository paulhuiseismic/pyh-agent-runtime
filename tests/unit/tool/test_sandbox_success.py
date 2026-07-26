"""T015 [US2]: 正常执行与参数传递。"""

import json

from kernel.tool import SandboxedTool


async def test_normal_execution_returns_stdout(echo_args_command):
    tool = SandboxedTool(name="echo", description="echo tool", command=echo_args_command)
    result = await tool.invoke({"query": "hello"}, tenant_id="tenant-a")
    assert json.loads(result) == {"query": "hello"}


async def test_arguments_correctly_passed_to_subprocess(echo_args_command):
    tool = SandboxedTool(name="echo", description="echo tool", command=echo_args_command)
    result = await tool.invoke({"a": 1, "b": [1, 2, 3]}, tenant_id="tenant-a")
    assert json.loads(result) == {"a": 1, "b": [1, 2, 3]}
