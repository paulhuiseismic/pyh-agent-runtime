"""tool 测试公共设施：示例脚本路径、短超时 SandboxLimits fixture。"""

import sys
from pathlib import Path

import pytest

from kernel.tool.sandbox_models import SandboxLimits

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _script_command(script_name: str) -> list[str]:
    return [sys.executable, str(_FIXTURES_DIR / script_name)]


@pytest.fixture
def echo_args_command() -> list[str]:
    return _script_command("echo_args.py")


@pytest.fixture
def sleep_forever_command() -> list[str]:
    return _script_command("sleep_forever.py")


@pytest.fixture
def exit_nonzero_command() -> list[str]:
    return _script_command("exit_nonzero.py")


@pytest.fixture
def grow_memory_command() -> list[str]:
    return _script_command("grow_memory.py")


@pytest.fixture
def short_timeout_limits() -> SandboxLimits:
    """供超时类测试使用的较小 timeout_seconds，加速测试执行。"""
    return SandboxLimits(timeout_seconds=0.3)
