# Research: plugin tool 插件机制 + sandbox

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md)

## R1. 子进程启动方式与资源限制注入点

- **Decision**: 不使用 `subprocess.Popen(preexec_fn=...)` 在父进程内注入资源限制。
  改为一个独立的"运行器"脚本 `kernel/tool/sandbox_runner.py`，通过
  `python -m kernel.tool.sandbox_runner <target_command> [args...]` 启动为一个
  全新子进程；运行器脚本自身在 POSIX 平台上调用 `resource.setrlimit()` 设置
  CPU 时间与地址空间（内存）上限后，用 `os.execvp()` 替换自身为目标命令；
  Windows 上跳过资源限制设置直接 `execvp`。
- **Rationale**: Python 官方文档明确警告 `preexec_fn` 在多线程程序中不安全
  （`asyncio.create_subprocess_exec` 底层依赖线程），在 fork 之后、exec 之前
  的窄窗口期只能调用异步信号安全的函数，容易死锁。用独立运行器进程规避了
  这个问题——父进程（asyncio 事件循环所在进程）只是正常地
  `create_subprocess_exec` 启动一个新 Python 解释器，资源限制设置发生在
  那个全新解释器进程的 main 线程里，不存在多线程 fork 风险。
- **Alternatives considered**: `preexec_fn`（有 asyncio 多线程风险，文档明确
  不推荐）；`subprocess.Popen` 的 `start_new_session` 等 POSIX-only 参数配合
  外部 `ulimit` shell 命令包一层（引入 shell 解析，增加参数转义的攻击面）。

## R2. 跨平台资源限制的能力边界（诚实声明，不伪造）

- **Decision**: CPU 时间与内存上限只在 POSIX（Linux/macOS）上通过 `resource`
  模块硬性生效；Windows 上这两项限制配置被接受（不报错），但不做任何强制
  ——文档与代码注释明确声明这一差异。超时是唯一在所有平台都强制生效的限制
  （通过 `asyncio.wait_for` + 进程终止实现，与操作系统无关）。测试中，
  CPU/内存超限场景用 `pytest.mark.skipif(sys.platform == "win32", reason=...)`
  显式跳过并注明原因，而不是让测试在 Windows 上产生误导性的"通过"或悄悄
  不覆盖这个场景。
- **Rationale**: spec FR-007 已明确"资源限制能力 MAY 因平台不同而具备不同
  程度的实际约束力"，但要求"配置接口本身必须存在、不允许配置为无限制"。
  在 Windows 上实现真正的硬性资源限制需要 Windows Job Objects API
  （通过 `pywin32` 或手写 `ctypes` 调用 kernel32），属于显著的新增复杂度或
  新依赖，而项目的生产目标平台是 Linux（001 起就已声明），Windows 只是
  本地开发环境。诚实标注这个能力缺口，比引入额外依赖或用轮询式软限制
  （如 `psutil` 定期检查后 kill，有延迟、不是硬限制）更符合宪法"最简实现"
  与"不引入未讨论依赖"的精神。
- **Alternatives considered**: 引入 `psutil` 做跨平台轮询式资源监控
  （新增依赖，且是"软"限制——存在检测延迟，与"限制"的语义有出入，
  需要用户确认是否接受新依赖，未在本次讨论中提出）；用 `pywin32` 实现
  Windows Job Objects（大幅增加 Windows 分支的实现复杂度，为一个非生产
  目标平台投入不成比例的工作量）。

## R3. 参数传递方式

- **Decision**: 调用方传入的 `arguments: dict` 经 `json.dumps()` 编码后，
  完整写入子进程的标准输入（stdin），目标命令自行从 stdin 读取并解析 JSON。
- **Rationale**: 命令行参数在不同 shell/操作系统下的转义规则不一致，且长度
  有限制；标准输入没有这些问题，且 JSON 是项目已经在 002（ReAct 思考输出）
  与 004（记忆提炼输出）中反复验证过的结构化交换格式，保持一致性。
- **Alternatives considered**: 命令行参数拼接（转义复杂、有长度上限，
  且 spec 原文虽提到"命令行参数"作为可选方式，但 stdin 是更简单可靠的
  唯一实现，符合最简原则——不需要同时支持两种传参方式）。

## R4. 输出大小与截断

- **Decision**: 读取子进程标准输出时设置上限（`SandboxLimits.max_output_bytes`，
  默认 1MB）；超出部分被截断，截断发生的事实通过在返回内容末尾追加一个
  明确的截断标记文本体现（不静默丢弃且不让调用方误以为输出完整）。
- **Rationale**: spec Edge Cases 明确要求"避免单次工具调用的返回值无限增长"；
  截断而非报错，是因为"输出过长"本身不算工具执行失败，只是需要限制返回
  内容的体量。
- **Alternatives considered**: 输出超限直接判定为失败（过于严格——很多正常
  工具的输出可能恰好较长，没必要因为体量就判定整次调用失败）。

## R5. 失败类型化的异常层级

- **Decision**:
  ```text
  SandboxError(Exception)                    # 所有沙箱相关失败的基类
  ├── SandboxInfraError                       # 沙箱层面的基础设施失败
  │   ├── SandboxTimeoutError                 # 携带 timeout_seconds
  │   ├── SandboxResourceExceededError        # 携带 resource_name, limit
  │   └── SandboxStartupError                 # 携带 detail（命令不存在/无权限等）
  └── SandboxToolExecutionError                # 非零退出码，工具自身业务失败；
                                                # 携带 exit_code, stderr_snippet
  ```
  全部通过 `SandboxedTool.invoke()` 直接抛出；002 `ReactEngine._invoke_tool`
  已有的 `except Exception` 捕获逻辑无需任何改动即可将其转为观察结果
  （FR-010/FR-013）。
- **Rationale**: 基类划分区分"沙箱基础设施问题"（超时/资源/启动失败）与
  "工具自身运行结果不理想"（非零退出码），调用方如果需要区分处理可以
  `except SandboxInfraError` 单独捕获，不需要区分时统一 `except SandboxError`
  即可；这个层级设计与 001 `ProviderError` 层级、002 `StepBudgetExceededError`
  与 provider 异常的区分模式一致，保持全项目异常设计风格统一。
- **Alternatives considered**: 单一异常类型 + 错误码字段（更简单但调用方
  无法用 `except` 做类型级别的区分，弱化了 Python 惯用的错误处理方式，
  与 001/002 已确立的风格不一致）。

## R6. ToolRegistry 的重名拒绝与错误类型

- **Decision**: 复用 `kernel.provider.errors.InvalidRequestError`（001 已定义）
  表达"注册前校验失败"，而不是新增一个专门的异常类型。
- **Rationale**: 重名注册本质上是"调用方传入了不合法的注册请求"，与 001
  provider 中"请求缺 tenant_id 时抛 InvalidRequestError"是同一类语义
  （发出实际操作前的参数校验失败）；复用已有异常类型避免为一个简单的
  校验场景新增类型，符合最简原则。
- **Alternatives considered**: 新增 `ToolAlreadyRegisteredError`（略微更精确，
  但为单一简单场景新增异常类型的收益不足以抵消额外的类型层级复杂度）。

## R7. 遥测标注方式

- **Decision**: 复用 001-004 已有的 tracer（同一 `kernel.provider` tracer
  name），每次 `SandboxedTool.invoke()` 发一个 `tool.invoke` span，属性含
  `tenant_id`、`tool_name`、`result_type`（success/timeout/resource_exceeded/
  startup_failed/nonzero_exit 之一）、`duration_seconds`。本 span 不涉及
  LLM 调用，无子 span（区别于 002/003/004 的父子 span 模式——沙箱执行是
  纯粹的子进程管理，不发起 provider 调用）。
- **Rationale**: 与既有遥测架构保持一致，无需引入第二套 tracer 配置面。
- **Alternatives considered**: 无——沙箱执行确实不涉及 LLM 调用，不存在
  父子 span 的适用场景。

## R8. 测试用示例脚本的实现方式

- **Decision**: 测试 fixture 脚本用纯 Python 标准库实现（`tests/unit/tool/
  fixtures/*.py`），通过 `sys.executable <script_path>` 方式作为
  `SandboxedTool` 的目标命令，保证跨平台一致可用，不依赖 shell 特定语法。
  `grow_memory.py`（大量分配内存触发资源超限）仅在 POSIX 测试中使用，
  Windows 测试跳过。
- **Rationale**: 用 Python 脚本而非 shell 脚本（`.sh`/`.bat`）保证同一份
  测试代码在 Windows/Linux/macOS 上行为一致，避免维护平台特定的脚本变体。
- **Alternatives considered**: 平台特定的 shell 脚本（需要维护两套，
  且 Windows 批处理与 POSIX shell 语法差异大，增加维护成本）。
