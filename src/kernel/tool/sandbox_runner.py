"""独立沙箱运行器（见 specs/005 research.md R1）。

作为一个全新子进程启动（`python -m kernel.tool.sandbox_runner <command...>`），
不与 asyncio 事件循环所在的父进程共享 fork/线程语义，规避 preexec_fn 的已知
风险。POSIX 上设置资源限制后用 os.execvp 替换自身为目标命令；execvp 失败
（命令不存在/无执行权限）无法被父进程跨进程捕获，故以保留退出码 127 退出，
父进程据此识别为 SandboxStartupError（见 data-model.md"运行器 ↔ 父进程的
失败识别协议"）。

资源限制通过环境变量传入（而非 argv，避免与目标命令自身的参数混淆）：
  SANDBOX_MAX_CPU_SECONDS
  SANDBOX_MAX_MEMORY_BYTES
"""

import os
import sys

_STARTUP_FAILURE_EXIT_CODE = 127


def _apply_posix_resource_limits() -> None:
    if sys.platform == "win32":
        return
    try:
        import resource
    except ImportError:
        return

    max_cpu_seconds = os.environ.get("SANDBOX_MAX_CPU_SECONDS")
    if max_cpu_seconds is not None:
        cpu_limit = int(float(max_cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))

    max_memory_bytes = os.environ.get("SANDBOX_MAX_MEMORY_BYTES")
    if max_memory_bytes is not None:
        mem_limit = int(max_memory_bytes)
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))


def main() -> None:
    command = sys.argv[1:]
    if not command:
        print("sandbox_runner: 缺少目标命令", file=sys.stderr)
        sys.exit(_STARTUP_FAILURE_EXIT_CODE)

    _apply_posix_resource_limits()

    try:
        os.execvp(command[0], command)
    except (OSError, FileNotFoundError, PermissionError) as exc:
        print(f"sandbox_runner: 启动目标命令失败: {exc}", file=sys.stderr)
        sys.exit(_STARTUP_FAILURE_EXIT_CODE)


if __name__ == "__main__":
    main()
