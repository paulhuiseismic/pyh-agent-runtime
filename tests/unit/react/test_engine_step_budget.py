"""T014-T016 [US2]: 步数耗尽终止、max_steps 校验、边界 max_steps=1。"""

import pytest

from kernel.provider import InvalidRequestError
from kernel.react import ReactEngine, StepBudgetExceededError
from tests.unit.react.conftest import MODEL, StubTool, always_call_tool_provider


def make_engine(price_table, tools=None):
    provider = always_call_tool_provider(price_table)
    return ReactEngine(provider=provider, tools=tools or {}, model=MODEL)


async def test_step_budget_exceeded_after_exact_steps(price_table):
    tool = StubTool("search", result="obs")
    engine = make_engine(price_table, tools={"search": tool})
    with pytest.raises(StepBudgetExceededError) as exc_info:
        await engine.run("goal", tenant_id="tenant-a", max_steps=3)
    assert exc_info.value.steps_executed == 3
    assert tool.call_count == 3  # 恰好执行 3 步，不超步


@pytest.mark.parametrize("max_steps", [0, -1, 1.5])
async def test_invalid_max_steps_rejected_before_any_call(price_table, max_steps):
    tool = StubTool("search", result="obs")
    engine = make_engine(price_table, tools={"search": tool})
    with pytest.raises(InvalidRequestError):
        await engine.run("goal", tenant_id="tenant-a", max_steps=max_steps)
    assert tool.call_count == 0  # 未触发任何调用


async def test_max_steps_one_terminates_immediately(price_table):
    tool = StubTool("search", result="obs")
    engine = make_engine(price_table, tools={"search": tool})
    with pytest.raises(StepBudgetExceededError) as exc_info:
        await engine.run("goal", tenant_id="tenant-a", max_steps=1)
    assert exc_info.value.steps_executed == 1
    assert tool.call_count == 1  # 不额外多跑一步
