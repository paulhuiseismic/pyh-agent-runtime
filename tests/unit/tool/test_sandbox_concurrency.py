"""T026: 并发调用同一 SandboxedTool 实例，互不串扰（spec Edge Cases 第 4 条）。"""

import asyncio
import json

from kernel.tool import SandboxedTool


async def test_concurrent_invocations_do_not_interfere(echo_args_command):
    tool = SandboxedTool(name="echo", description="echo", command=echo_args_command)

    results = await asyncio.gather(
        *(tool.invoke({"index": i}, tenant_id="tenant-a") for i in range(8))
    )

    parsed = [json.loads(r) for r in results]
    assert sorted(p["index"] for p in parsed) == list(range(8))
