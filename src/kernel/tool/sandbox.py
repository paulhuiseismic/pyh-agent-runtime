"""SandboxedTool：沙箱执行编排（见 specs/005 data-model.md 状态流转）。"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

from kernel.tool.sandbox_models import (
    SandboxLimits,
    SandboxResourceExceededError,
    SandboxStartupError,
    SandboxTimeoutError,
    SandboxToolExecutionError,
)

_STARTUP_FAILURE_EXIT_CODE = 127
_STDERR_SNIPPET_MAX_CHARS = 500

# POSIX 信号编号 → 资源名映射（见 data-model.md 状态流转、research.md R2/R5）。
# SIGKILL（9）通常由 RLIMIT_AS（内存）超限触发；SIGXCPU（24，Linux 上的常见值）
# 由 RLIMIT_CPU 超限触发。硬编码数值而非依赖 signal 模块的平台可用性，
# 因为该分支只在 POSIX 上可能触发（Windows 不产生负数 returncode）。
_SIGXCPU = 24
_SIGKILL = 9


class SandboxedTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        command: list[str],
        limits: SandboxLimits = SandboxLimits(),
    ) -> None:
        self.name = name
        self.description = description
        self._command = command
        self._limits = limits

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        workdir = tempfile.mkdtemp(prefix="sandbox-")
        try:
            return await self._run(arguments, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _run(self, arguments: dict, workdir: str) -> str:
        env = dict(os.environ)
        env["SANDBOX_MAX_CPU_SECONDS"] = str(self._limits.max_cpu_seconds)
        env["SANDBOX_MAX_MEMORY_BYTES"] = str(int(self._limits.max_memory_bytes))

        runner_cmd = [sys.executable, "-m", "kernel.tool.sandbox_runner", *self._command]

        process = await asyncio.create_subprocess_exec(
            *runner_cmd,
            cwd=workdir,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        input_bytes = json.dumps(arguments).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=input_bytes),
                timeout=self._limits.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise SandboxTimeoutError(self._limits.timeout_seconds)

        returncode = process.returncode
        if returncode == _STARTUP_FAILURE_EXIT_CODE:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise SandboxStartupError(detail)

        if returncode < 0:
            # POSIX 信号终止（资源限制触发），与普通非零退出码的业务失败区分
            signal_num = -returncode
            if signal_num == _SIGXCPU:
                raise SandboxResourceExceededError("cpu", self._limits.max_cpu_seconds)
            raise SandboxResourceExceededError("memory", self._limits.max_memory_bytes)

        if returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            raise SandboxToolExecutionError(
                exit_code=returncode, stderr_snippet=stderr_text[:_STDERR_SNIPPET_MAX_CHARS]
            )

        return stdout.decode("utf-8", errors="replace")
