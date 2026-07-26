"""SandboxedTool：沙箱执行编排（见 specs/005 data-model.md 状态流转）。"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

from kernel.tool.sandbox_models import (
    SandboxLimits,
    SandboxStartupError,
    SandboxToolExecutionError,
)

_STARTUP_FAILURE_EXIT_CODE = 127
_STDERR_SNIPPET_MAX_CHARS = 500


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
        stdout, stderr = await process.communicate(input=input_bytes)

        returncode = process.returncode
        if returncode == _STARTUP_FAILURE_EXIT_CODE:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise SandboxStartupError(detail)

        if returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            raise SandboxToolExecutionError(
                exit_code=returncode, stderr_snippet=stderr_text[:_STDERR_SNIPPET_MAX_CHARS]
            )

        return stdout.decode("utf-8", errors="replace")
