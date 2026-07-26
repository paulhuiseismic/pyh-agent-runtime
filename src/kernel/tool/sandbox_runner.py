"""独立沙箱运行器（见 specs/005 research.md R1）。

作为一个全新子进程启动（`python -m kernel.tool.sandbox_runner <command...>`），
不与 asyncio 事件循环所在的父进程共享 fork/线程语义，规避 preexec_fn 的已知
风险。POSIX 上设置资源限制（对自身生效，fork+exec 出的子进程会继承）后用
subprocess.run() 执行目标命令并显式传播退出码；若目标进程被信号终止
（如 RLIMIT_AS/RLIMIT_CPU 触发的 SIGKILL/SIGXCPU），本运行器对自身重新
发送同一信号，使等待该运行器进程的父进程观察到与"进程本身被该信号终止"
一致的负数 returncode 语义。

（注：最初设计使用 os.execvp 直接替换进程，但实测发现 Windows 上
os.execvp/execv 系列的退出码传播存在问题——父进程会得到 0 而非目标进程的
真实退出码。改为 subprocess.run + 显式 sys.exit 规避此问题，且资源限制
仍能通过 POSIX 的 fork+exec 继承机制正常生效，不依赖 execvp 的进程替换。）

目标命令启动失败（不存在/无执行权限）无法被父进程跨进程捕获，故以保留
退出码 127 退出，父进程据此识别为 SandboxStartupError（见 data-model.md
"运行器 ↔ 父进程的失败识别协议"）。

资源限制通过环境变量传入（而非 argv，避免与目标命令自身的参数混淆）：
  SANDBOX_MAX_CPU_SECONDS
  SANDBOX_MAX_MEMORY_BYTES
"""

import os
import subprocess
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
        result = subprocess.run(command)
    except (OSError, FileNotFoundError, PermissionError) as exc:
        print(f"sandbox_runner: 启动目标命令失败: {exc}", file=sys.stderr)
        sys.exit(_STARTUP_FAILURE_EXIT_CODE)

    returncode = result.returncode
    if returncode < 0:
        # POSIX: 目标进程被信号终止（如资源限制触发）。对自身重发同一信号，
        # 使父进程观察到与"运行器自身被该信号终止"一致的负数 returncode。
        signal_num = -returncode
        os.kill(os.getpid(), signal_num)
        # 上一行通常不会返回（进程已被信号终止）；仅作兜底。
        sys.exit(128 + signal_num)

    sys.exit(returncode)


if __name__ == "__main__":
    main()
