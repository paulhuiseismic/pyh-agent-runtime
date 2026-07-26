# Data Model: plugin tool 插件机制 + sandbox

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

## SandboxLimits（配置，frozen dataclass，见 `sandbox_models.py`）

| 字段 | 类型 | 默认值 | 约束 |
|------|------|--------|------|
| timeout_seconds | float | 30.0 | > 0（所有平台强制生效，research.md R2） |
| max_cpu_seconds | float | 10.0 | > 0（仅 POSIX 硬性生效） |
| max_memory_bytes | int | 268435456（256MB） | > 0（仅 POSIX 硬性生效） |
| max_output_bytes | int | 1048576（1MB） | > 0（输出截断阈值，所有平台生效） |

任何字段 ≤ 0 → `InvalidRequestError`（复用 001 异常，构造时拒绝）。

## 异常层级（`sandbox_models.py`，见 research.md R5）

```text
SandboxError(Exception)
├── SandboxInfraError(SandboxError)
│   ├── SandboxTimeoutError          # timeout_seconds
│   ├── SandboxResourceExceededError # resource_name: "cpu"|"memory", limit
│   └── SandboxStartupError          # detail: str
└── SandboxToolExecutionError(SandboxError)  # exit_code: int, stderr_snippet: str
```

所有异常均携带足够的诊断信息（对应字段），供调用方（或 002 ReactEngine
转化出的 Observation.content）展示失败原因。

## ToolRegistry（`registry.py`）

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None: ...   # 重名 → InvalidRequestError
    def get(self, name: str) -> Tool | None: ...    # 未找到 → None（不抛异常）
    def list_tools(self) -> list[Tool]: ...
    def as_dict(self) -> dict[str, Tool]: ...        # 供 002 ReactEngine(tools=...) 直接使用
```

## SandboxedTool（`sandbox.py`，实现 001 冻结的 `Tool` Protocol）

```python
class SandboxedTool:
    name: str
    description: str

    def __init__(
        self, *, name: str, description: str, command: list[str],
        limits: SandboxLimits = SandboxLimits(),
    ) -> None: ...

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str: ...
```

`command` 是目标可执行文件与固定参数的列表（如 `["python", "/path/to/tool.py"]`）；
调用方传入的 `arguments` 不拼接进 `command`，而是通过 stdin 传递（research.md R3）。

## 运行器 ↔ 父进程的失败识别协议（sandbox_runner.py，见 research.md R1）

`sandbox_runner.py` 内的 `os.execvp()` 若失败（目标命令不存在/无执行权限），
失败发生在**子进程内部**——父进程无法跨进程边界捕获这个 Python 异常，只能
看到子进程以某个退出码结束。因此约定一个**保留退出码 127**（沿用 shell
"command not found" 的惯例）：运行器脚本 MUST 捕获 `execvp` 抛出的
`OSError`/`FileNotFoundError`/`PermissionError`，打印诊断信息到 stderr 后
以退出码 127 退出；父进程（`sandbox.py`）看到子进程以退出码 **127** 结束时，
MUST 判定为 `SandboxStartupError`（而不是尝试捕获跨进程异常）。

子进程若因资源限制被内核终止（`RLIMIT_CPU`/`RLIMIT_AS` 触发），
`asyncio.subprocess` 报告的 `returncode` 是**负的信号编号**
（如 `-9` 对应 SIGKILL、`-24` 对应 SIGXCPU），而非正数退出码——这与
"正常运行但业务失败"的正数非零退出码是两类完全不同的信号。

## 状态流转（一次 `invoke()`）

```text
invoke(arguments, tenant_id)
  → 创建专用临时工作目录（tempfile.mkdtemp，FR-008）
  → 启动子进程: python -m kernel.tool.sandbox_runner <command...>
      cwd=临时工作目录, stdin=PIPE, stdout=PIPE, stderr=PIPE
  → 写入 json.dumps(arguments) 到 stdin 并关闭
  → asyncio.wait_for(等待进程结束, timeout=limits.timeout_seconds)
    ├─ 超时 → 终止子进程 → SandboxTimeoutError(timeout_seconds)
  → 读取 stdout（按 max_output_bytes 截断，超出部分追加截断标记，research.md R4）
  → 判定 returncode:
      ├─ returncode == 127 → SandboxStartupError（运行器捕获的 execvp 失败，见上）
      ├─ returncode < 0（POSIX 信号终止，如 -9/SIGKILL、-24/SIGXCPU）
      │   → SandboxResourceExceededError(resource_name, limit)
      │     （信号 → 资源名的映射：SIGKILL 关联 max_memory_bytes 触发的
      │     RLIMIT_AS，SIGXCPU 关联 max_cpu_seconds 触发的 RLIMIT_CPU；
      │     两者均仅可能在 POSIX 平台出现，Windows 上不会走到这一支）
      ├─ returncode > 0（正常运行但业务失败）→ SandboxToolExecutionError
      │     (exit_code, stderr_snippet)
      └─ returncode == 0 → 返回 stdout 内容（str）
  → 清理临时工作目录
  （全路径 finally：发出 tool.invoke span，见 research.md R7）
```

## 遥测 span 契约（`tool.invoke`，见 research.md R7）

| 属性 | 值 |
|------|-----|
| span name | `tool.invoke` |
| `tenant_id` | 调用方传入的 tenant_id |
| `tool_name` | 该 SandboxedTool 实例的 name |
| `result_type` | `success` / `timeout` / `resource_exceeded` / `startup_failed` / `nonzero_exit` |
| `duration_seconds` | 本次调用实际耗时 |
| 父子关系 | 无子 span（不涉及 LLM 调用） |
| span status | 成功 OK；任意失败类型 ERROR + 异常类名 |
