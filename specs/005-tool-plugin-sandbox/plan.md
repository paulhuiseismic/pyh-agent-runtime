# Implementation Plan: plugin tool 插件机制 + sandbox

**Branch**: `005-tool-plugin-sandbox` | **Date**: 2026-07-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-tool-plugin-sandbox/spec.md`

## Summary

在 `src/kernel/tool/` 中新增 `ToolRegistry`（按名称注册/查找/列出，重名拒绝）与
`SandboxedTool`（实现 001 冻结的 `Tool` Protocol，`invoke()` 内部通过一个独立的
"沙箱运行器"子进程执行调用方配置的外部命令）。资源限制采用"运行器脚本 +
`resource` 模块"的 POSIX 实现（CPU 时间、地址空间上限），Windows 上不做
硬性资源强制（仅超时在所有平台生效），这一差异在 research 中明确记录并在
测试中用平台条件跳过而非静默忽略。参数经 JSON 编码通过子进程 stdin 传递，
输出按上限截断。四类失败（超时/资源超限/启动失败/非零退出码）各自类型化，
全部通过现有 `Tool.invoke()` 异常机制反馈，002 `ReactEngine` 无需改动即可
兼容（其 `_invoke_tool` 已捕获任意异常转为观察结果）。

## Technical Context

**Language/Version**: Python 3.12（延续 001-004）

**Primary Dependencies**: 零新增——`resource`（POSIX 标准库，条件导入）、
`asyncio.create_subprocess_exec`（标准库）、`tempfile`（标准库）、
`opentelemetry-api`/`-sdk`（已有依赖）

**Storage**: N/A（本 feature 无持久化）

**Testing**: pytest + pytest-asyncio；用本地临时 Python 脚本作为沙箱执行的
示例目标（正常退出/慢速/耗内存/非零退出码/不存在的命令），CPU/内存限制类
测试在非 POSIX 平台（Windows）用 `pytest.mark.skipif` 跳过并注明原因
（research.md R2），超时类测试在所有平台运行

**Target Platform**: 同 001-004（Linux server 生产 / Windows 本地开发）；
本 feature 是唯一一个"生产平台能力强于开发平台"的 feature（资源限制在
Linux 上硬性生效，Windows 上不生效），需在文档与测试中显式标注

**Project Type**: library（内核 tool 子模块的完整实现，替换 001 的 EchoTool 占位）

**Performance Goals**: 沙箱调度自身开销（不含目标命令执行时间）<50ms
（参考值，不作为验收标准、不设基准测试任务，同 001-004 的处理方式）

**Constraints**: 不改变 001/002 冻结的 `Tool` Protocol 签名（FR-013）；
不提供网络隔离，需在代码注释与文档中明确声明（FR-009）；任何限额
（超时/CPU/内存/输出大小）不允许配置为"无限制"（呼应宪法原则 IV 的精神，
扩展到沙箱执行范畴）

**Scale/Scope**: 约 6-7 个源文件 + 单元测试 + 若干个测试用示例脚本；
不涉及平台层、不涉及 MCP（拆分到未来 006）、不涉及容器/gVisor

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | tool 子模块零 import 平台层；ToolRegistry/SandboxedTool 均为纯内核实现 | ✅ 通过 |
| II. 最简实现 | 资源限制用标准库 `resource` + 独立运行器脚本，不引入 psutil/pywin32 等新依赖；Windows 上诚实地不做强制而非伪造实现 | ✅ 通过 |
| III. 组装优先 | 零新增第三方依赖，全部基于标准库能力组装 | ✅ 通过 |
| IV. 超时与成本上限 | 沙箱执行超时在所有平台强制生效（FR-006）；CPU/内存/输出大小上限均不允许"无限制"配置 | ✅ 通过 |
| V. OTel GenAI 可观测 | 每次沙箱执行发 `tool.invoke` span，含 tenant_id/工具名/结果类型/耗时（FR-011） | ✅ 通过 |
| VI. 测试与安全边界 | 全场景单测（含平台条件跳过并注明原因，非静默跳过）；ToolRegistry 拒绝重名注册 | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入新依赖，六项门禁维持通过。Windows
资源限制的能力缺口已在 Technical Context 与 research.md 中显式记录，
不是被忽略的问题。

## Project Structure

### Documentation (this feature)

```text
specs/005-tool-plugin-sandbox/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── tool-registry-sandbox-api.md  # 对上层暴露的接口契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/kernel/tool/
├── __init__.py            # 导出 Tool Protocol（001 冻结）、ToolRegistry、
│                           # SandboxedTool、SandboxLimits、异常层级；保留 EchoTool
├── registry.py             # ToolRegistry：register/get/list_tools
├── sandbox_models.py        # SandboxLimits（frozen dataclass，安全默认值）、
│                           # 异常层级（SandboxError 及四个子类）
├── sandbox_runner.py        # 独立运行器脚本：POSIX 上设置 resource limits 后
│                           # os.execvp 目标命令；Windows 上直接 exec（无限制）
├── sandbox.py                # SandboxedTool：invoke() 编排——建临时工作目录、
│                           # 启动运行器子进程、写 stdin、读 stdout（截断）、
│                           # 超时/退出码判定、清理
└── telemetry.py             # tool.invoke span：tenant_id/工具名/结果类型/耗时

tests/unit/tool/
├── fixtures/                          # 测试用示例脚本
│   ├── echo_args.py                    # 正常退出：回显传入的 JSON 参数
│   ├── sleep_forever.py                # 故意长时间运行（触发超时）
│   ├── grow_memory.py                  # 故意大量分配内存（触发资源超限，仅 POSIX）
│   └── exit_nonzero.py                 # 以非零退出码退出
├── conftest.py                         # 示例脚本路径 fixture、SandboxLimits fixture
├── test_registry.py                    # US1：注册/查找/列出、重名拒绝、未找到
├── test_sandbox_success.py             # US2：正常执行、参数传递、输出截断
├── test_sandbox_business_failure.py    # US2：非零退出码、启动失败（命令不存在）
├── test_sandbox_timeout.py             # US3：超时强制终止（所有平台）
├── test_sandbox_resource_limit.py      # US3：CPU/内存超限（仅 POSIX，skipif Windows）
└── test_sandbox_telemetry.py           # 遥测：span 属性、结果类型可区分、遥测容错
```

**Structure Decision**: 延续 001-004 的单包 library 布局；`tool` 子包内部
按职责拆分（注册中心/沙箱配置与异常/运行器/编排/遥测各一文件），运行器
脚本（`sandbox_runner.py`）作为独立可执行模块（`python -m kernel.tool.
sandbox_runner ...`），不与 asyncio 事件循环所在进程共享 fork 语义，
规避 `preexec_fn` 在多线程/asyncio 环境下的已知风险（research.md R1）。
