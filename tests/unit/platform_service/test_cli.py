import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service import cli
from platform_service.agent_service import AgentService
from tests.unit.platform_service.conftest import erroring_provider, slow_stub_provider, stub_provider

MODEL = "platform-test-model"


def test_build_arg_parser_parses_all_options():
    args = cli.build_arg_parser().parse_args(["问题", "--session-id", "s1", "--config", "c.json"])
    assert args.goal == "问题"
    assert args.session_id == "s1"
    assert args.config == "c.json"


def test_build_arg_parser_defaults():
    args = cli.build_arg_parser().parse_args(["问题"])
    assert args.session_id is None
    assert args.config is None


def test_resolve_api_key_missing_returns_none():
    assert cli.resolve_api_key({}) is None


def test_resolve_api_key_present():
    assert cli.resolve_api_key({"PLATFORM_SERVICE_API_KEY": "k"}) == "k"


async def _build_service(config, provider):
    session_memory = SqliteMemory(
        db_path=":memory:", provider=provider, model=config.model
    )
    long_term_memory = LongTermMemory(
        db_path=":memory:", provider=provider, model=config.model
    )
    try:
        service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=config,
        )
        yield service
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


def _write_config_file(path: Path, platform_config) -> None:
    payload = {
        "tenants": [
            {
                "api_key": t.api_key,
                "tenant_id": t.tenant_id,
                "max_concurrent_requests": t.max_concurrent_requests,
            }
            for t in platform_config.tenants
        ],
        "global_max_concurrent_requests": platform_config.global_max_concurrent_requests,
        "request_timeout_seconds": platform_config.request_timeout_seconds,
        "model": platform_config.model,
        "max_steps": platform_config.max_steps,
        "provider_base_url": platform_config.provider_base_url,
        "price_table": {
            MODEL: {"input_per_1k_usd": 0.01, "output_per_1k_usd": 0.03},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


async def test_run_success(platform_config, tmp_path):
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, platform_config)

    async for service in _build_service(platform_config, stub_provider("42")):
        exit_code, stdout, stderr = await cli.run(
            ["1+1=?"],
            {"PLATFORM_SERVICE_API_KEY": "key-a", "PLATFORM_SERVICE_CONFIG": str(config_path)},
            agent_service=service,
        )
    assert exit_code == cli.EXIT_SUCCESS
    assert stdout == "42\n"
    assert stderr == ""


async def test_run_kernel_error(platform_config, tmp_path):
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, platform_config)

    async for service in _build_service(platform_config, erroring_provider(RuntimeError("boom"))):
        exit_code, stdout, stderr = await cli.run(
            ["问题"],
            {"PLATFORM_SERVICE_API_KEY": "key-a", "PLATFORM_SERVICE_CONFIG": str(config_path)},
            agent_service=service,
        )
    assert exit_code == cli.EXIT_KERNEL_ERROR
    assert stdout == ""
    assert stderr != ""


async def test_run_timeout(platform_config, tmp_path):
    import dataclasses

    fast_timeout_config = dataclasses.replace(platform_config, request_timeout_seconds=0.05)
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, fast_timeout_config)

    async for service in _build_service(fast_timeout_config, slow_stub_provider(1.0)):
        exit_code, stdout, stderr = await cli.run(
            ["问题"],
            {"PLATFORM_SERVICE_API_KEY": "key-a", "PLATFORM_SERVICE_CONFIG": str(config_path)},
            agent_service=service,
        )
    assert exit_code == cli.EXIT_TIMEOUT
    assert stdout == ""
    assert stderr != ""


async def test_run_session_continuity(platform_config, tmp_path):
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, platform_config)
    db_path = str(tmp_path / "session.db")

    provider = stub_provider("回答")
    session_memory = SqliteMemory(db_path=db_path, provider=provider, model=platform_config.model)
    long_term_memory = LongTermMemory(
        db_path=str(tmp_path / "long_term.db"), provider=provider, model=platform_config.model
    )
    try:
        service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=platform_config,
        )
        env = {"PLATFORM_SERVICE_API_KEY": "key-a", "PLATFORM_SERVICE_CONFIG": str(config_path)}

        await cli.run(["我叫小明", "--session-id", "s1"], env, agent_service=service)

        history = await session_memory.load("s1", tenant_id="tenant-a")
        assert len(history) == 2
        assert history[0].content == "我叫小明"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


@pytest.mark.smoke
def test_module_invocable_as_subprocess():
    import os

    env = dict(os.environ)
    env.pop("PLATFORM_SERVICE_API_KEY", None)
    env.pop("PLATFORM_SERVICE_CONFIG", None)
    result = subprocess.run(
        [sys.executable, "-m", "platform_service.cli", "问题"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
