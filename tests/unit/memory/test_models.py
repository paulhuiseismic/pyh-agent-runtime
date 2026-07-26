"""T006: ContextBudget 校验单元测试。"""

import pytest

from kernel.memory.models import (
    DEFAULT_KEEP_RECENT_MESSAGES,
    DEFAULT_MAX_CONTEXT_TOKENS,
    ContextBudget,
)
from kernel.provider.errors import InvalidRequestError


def test_default_values():
    budget = ContextBudget()
    assert budget.max_context_tokens == DEFAULT_MAX_CONTEXT_TOKENS
    assert budget.keep_recent_messages == DEFAULT_KEEP_RECENT_MESSAGES


@pytest.mark.parametrize("field,value", [
    ("max_context_tokens", 0),
    ("max_context_tokens", -1),
    ("keep_recent_messages", 0),
    ("keep_recent_messages", -5),
    ("max_context_tokens", 1.5),
])
def test_non_positive_fields_rejected(field, value):
    with pytest.raises(InvalidRequestError):
        ContextBudget(**{field: value})
