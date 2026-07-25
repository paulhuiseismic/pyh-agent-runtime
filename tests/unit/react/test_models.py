"""T006: models 单元测试。"""

from kernel.react.models import Observation, StepBudgetExceededError


def test_observation_construction():
    obs = Observation(success=True, content="ok")
    assert obs.success is True
    assert obs.content == "ok"


def test_step_budget_exceeded_error_fields():
    err = StepBudgetExceededError(steps_executed=3, last_observation="last obs")
    assert err.steps_executed == 3
    assert err.last_observation == "last obs"
    assert "3" in str(err)
