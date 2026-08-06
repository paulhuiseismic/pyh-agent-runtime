"""CLI 入口：与 app.py 并列的另一个薄适配层，复用同一个 `AgentService`
处理路径（契约见 specs/008-cli-entrypoint/contracts/cli-contract.md）。

不复用 007 的 `ConcurrencyScheduler`——单进程单次调用没有真实的并发上限
场景需要保护，引入它只会产生一段无法被真实触发的检查（research.md R3）。
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping

from kernel.provider.errors import InvalidRequestError
from platform_service.agent_service import AgentService, build_agent_service
from platform_service.auth import resolve_tenant
from platform_service.config import load_config_from_file
from platform_service.errors import AuthenticationError
from platform_service.models import AgentRunRequest
from platform_service.telemetry import platform_request_span

EXIT_SUCCESS = 0
EXIT_MISSING_API_KEY = 1
EXIT_AUTH_FAILED = 2
EXIT_CONFIG_INVALID = 3
EXIT_VALIDATION_FAILED = 4
EXIT_TIMEOUT = 5
EXIT_KERNEL_ERROR = 6

_API_KEY_ENV_VAR = "PLATFORM_SERVICE_API_KEY"
_CONFIG_ENV_VAR = "PLATFORM_SERVICE_CONFIG"


class _CliFailure(Exception):
    """内部信号：携带退出码与 stderr 文本，跨越 `platform_request_span`
    的 `with` 块传递（span 需要在异常路径下也能记录 result 属性并正常
    退出，见 telemetry.py 的行为契约）。"""

    def __init__(self, exit_code: int, stderr_text: str) -> None:
        self.exit_code = exit_code
        self.stderr_text = stderr_text


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyh-agent")
    parser.add_argument("goal", help="要提交给 agent 的目标/问题文本")
    parser.add_argument("--session-id", dest="session_id", default=None)
    parser.add_argument("--config", dest="config", default=None)
    return parser


def resolve_api_key(env: Mapping[str, str]) -> str | None:
    api_key = env.get(_API_KEY_ENV_VAR)
    return api_key or None


async def run(
    argv: list[str],
    env: Mapping[str, str],
    *,
    agent_service: AgentService | None = None,
) -> tuple[int, str, str]:
    args = build_arg_parser().parse_args(argv)

    config_path = args.config or env.get(_CONFIG_ENV_VAR)
    if not config_path:
        return (
            EXIT_CONFIG_INVALID,
            "",
            f"错误: 未提供配置文件路径（--config 或 {_CONFIG_ENV_VAR} 环境变量）\n",
        )

    try:
        config = load_config_from_file(config_path)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, InvalidRequestError) as exc:
        return (EXIT_CONFIG_INVALID, "", f"错误: 平台配置无效: {exc}\n")

    api_key = resolve_api_key(env)
    if not api_key:
        return (
            EXIT_MISSING_API_KEY,
            "",
            f"错误: 未提供 API Key（{_API_KEY_ENV_VAR} 环境变量未设置）\n",
        )

    try:
        tenant_id = resolve_tenant(api_key, config)
    except AuthenticationError as exc:
        return (EXIT_AUTH_FAILED, "", f"错误: 身份识别失败: {exc}\n")

    if not args.goal.strip():
        return (EXIT_VALIDATION_FAILED, "", "错误: 问题不能为空\n")

    service = agent_service
    if service is None:
        service = await build_agent_service(config)

    request = AgentRunRequest(goal=args.goal, session_id=args.session_id)

    try:
        with platform_request_span(tenant_id=tenant_id, session_id=args.session_id) as span:
            try:
                result = await asyncio.wait_for(
                    service.handle(request, tenant_id=tenant_id),
                    timeout=config.request_timeout_seconds,
                )
            except asyncio.TimeoutError:
                span.set_result("timeout")
                raise _CliFailure(
                    EXIT_TIMEOUT,
                    f"错误: 请求处理超时（超过 {config.request_timeout_seconds}s）\n",
                ) from None
            except Exception as exc:
                span.set_result("kernel_error")
                raise _CliFailure(EXIT_KERNEL_ERROR, f"错误: 内核处理失败: {exc}\n") from exc

            span.set_result("success")
            return (EXIT_SUCCESS, result.answer + "\n", "")
    except _CliFailure as failure:
        return (failure.exit_code, "", failure.stderr_text)


def main() -> None:
    exit_code, stdout_text, stderr_text = asyncio.run(run(sys.argv[1:], os.environ))
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
