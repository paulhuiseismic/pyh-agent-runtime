# Implementation Plan: CLI 入口（复用平台服务层）

**Branch**: `008-cli-entrypoint` | **Date**: 2026-08-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-cli-entrypoint/spec.md`

## Summary

在 007 已建立的 `src/platform_service/` 包内新增第二个薄适配模块
`cli.py`（与 `app.py` 并列，二者都只做"外部调用形式 ↔ `AgentService`"的
适配，不下沉任何业务逻辑）。CLI 复用 007 的 `PlatformConfig`/
`load_config_from_file`/`build_agent_service`/`resolve_tenant`/
`AgentService` 全部既有实现，零改动、零复制；唯一新增的是"命令行参数与
环境变量 → 调用 `AgentService.handle()` → 终端可读输出"这一层胶水代码，
以及与之对应的进程退出码约定。CLI **不**复用 007 的
`ConcurrencyScheduler`——单进程单次调用没有真实的并发上限场景需要保护，
引入它只会产生一段正常情况下必然通过、无法被真实触发的死代码，属于
"为未来假设场景预留"的过度设计，`/speckit-analyze` 判定为违反宪法
原则 II 的 CRITICAL 问题（F1）后移除，详见 research.md R3。CLI 与 REST
两个入口在 `AgentService.handle()` 这一行为不变的边界上完全对齐
（呼应 007 FR-003/SC-006 与本 feature 的 SC-003）。

## Technical Context

**Language/Version**: Python 3.12（延续 001-007）

**Primary Dependencies**: 无新增第三方依赖——CLI 参数解析使用标准库
`argparse`；复用 007 已引入的 `fastapi`/`uvicorn`（仅 REST 侧使用，CLI
不依赖它们）、`httpx`/`opentelemetry-*`/`aiosqlite`/`mcp`（经由
`AgentService`/`build_agent_service` 间接复用）

**Storage**: 复用 007 已交付的 `SqliteMemory`/`LongTermMemory`（同一份
`PlatformConfig.session_memory_db_path`/`long_term_memory_db_path`
配置项，CLI 与 REST 若指向同一配置文件即共享同一组数据库文件）；不新增
存储

**Testing**: pytest + pytest-asyncio；CLI 的可测试单元是一个接受
`argv`/环境变量字典/可注入 `AgentService`（测试用 stub provider 驱动）
的内部异步函数，返回「退出码 + 捕获的 stdout/stderr 文本」，不通过真实
子进程调用（避免网络/进程管理开销，延续 001-007 的 stub 化测试风格）；
额外补充一个使用真实子进程（`subprocess`）调用一次控制台入口点的最小
冒烟测试，验证 `pyproject.toml` 的 console script 声明确实可用

**Target Platform**: 同 001-007（Linux server 生产 / Windows 本地开发）

**Project Type**: cli（在既有 007 `platform_service` 平台层包内新增的
第二个对外入口，不新建独立顶层包）

**Performance Goals**: 不设精确基准，同 007；单次命令执行的耗时上限由
`PlatformConfig.request_timeout_seconds` 显式约束（复用 007 FR-009）

**Constraints**: MUST NOT 修改 007 已冻结的 `AgentService`/`PlatformConfig`/
`resolve_tenant`/`build_agent_service` 的任何签名或行为（spec.md
FR-003）；CLI 侧新增代码仅可"调用"这些既有组件，不得复制其内部逻辑；
CLI MUST NOT 引入 007 的 `ConcurrencyScheduler`——单进程单次调用场景下
该组件无法被真实触发，引入即违反宪法原则 II（`/speckit-analyze` F1，
research.md R3）；租户 API Key MUST 通过环境变量传递，不出现在命令行
参数中（spec.md FR-002，避免 shell 历史/进程列表泄露）

**Scale/Scope**: 1 个新源文件（`platform_service/cli.py`）+ `pyproject.toml`
新增一个 console script 入口点 + 单元测试（含一个子进程冒烟测试）+
`examples/` 下一个演示脚本；不涉及 REPL 交互模式、不涉及 JSON 输出、
不涉及跨进程并发协调（spec.md Assumptions）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | `cli.py` 与 `app.py` 一样只单向 import `platform_service.*`/`kernel.*`；内核代码零改动 | ✅ 通过 |
| II. 最简实现 | 用标准库 `argparse`，不引入第三方 CLI 框架（Click/Typer 等）；不实现 REPL、不实现 JSON 输出，严格对齐 spec 已确认的最简范围；不复用 007 `ConcurrencyScheduler`——单进程单次调用场景下该组件无法被真实触发，引入即是"为未来假设场景预留"的过度设计（`/speckit-analyze` F1 修正，research.md R3） | ✅ 通过 |
| III. 组装优先 | 无新增第三方依赖，无需更新 THIRD_PARTY.md | ✅ 通过 |
| IV. 超时与成本上限 | 复用 007 `PlatformConfig.request_timeout_seconds`（`asyncio.wait_for` 包裹 `AgentService.handle()`，与 `app.py` 完全一致的超时语义），不新增任何"无限制"默认值 | ✅ 通过 |
| V. OTel GenAI 可观测 | 复用 `AgentService.handle()`/内核既有 span；CLI 侧新增一个 `platform.request`（与 007 REST 入口同名同结构）请求级 span，标注 `tenant_id`，保证 CLI 触发的调用链路可观测性与 REST 入口对齐（呼应 spec.md FR-007/SC-004） | ✅ 通过 |
| VI. 测试与安全边界 | `cli.py` 属于平台层胶水代码而非内核模块，仍按宪法附加约束补充单元测试（覆盖成功/各类失败退出码）；不引入无界循环，`max_steps`/超时均来自既有 `PlatformConfig` 校验 | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入任何新依赖或对 007 既有组件的
修改，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/008-cli-entrypoint/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── cli-contract.md   # CLI 命令行契约（参数/环境变量/退出码/输出格式）
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/platform_service/
├── __init__.py             # 包级导出：新增导出 cli 模块的 main 入口（供
│                           # console script 与测试引用）
└── cli.py                  # 新增：CLI 适配层
                              # - build_arg_parser()：argparse，定位参数
                              #   goal（必填）、--session-id（可选）、
                              #   --config（可选，缺省读 PLATFORM_SERVICE_CONFIG
                              #   环境变量）
                              # - resolve_api_key(env)：读取
                              #   PLATFORM_SERVICE_API_KEY 环境变量，未设置
                              #   返回 None（由调用方判定为"未提供 API Key"
                              #   失败，不触碰 AgentService/内核）
                              # - async def run(argv, env, *, agent_service=None)
                              #   -> tuple[int, str, str]（退出码、stdout 文本、
                              #   stderr 文本）：核心可测试逻辑，串联
                              #   load_config_from_file → resolve_tenant →
                              #   asyncio.wait_for(agent_service.handle(...))
                              #（不经过 ConcurrencyScheduler，research.md R3）；
                              #   agent_service 参数供测试注入 stub，未提供
                              #   时按 config 调用 build_agent_service()
                              #   （生产路径）
                              # - def main() -> NoReturn：包装 run()，读取
                              #   sys.argv/os.environ，打印到 sys.stdout/
                              #   sys.stderr，sys.exit(exit_code)
                              # - 退出码常量：EXIT_SUCCESS=0、
                              #   EXIT_MISSING_API_KEY/EXIT_AUTH_FAILED/
                              #   EXIT_CONFIG_INVALID/EXIT_VALIDATION_FAILED/
                              #   EXIT_TIMEOUT/EXIT_KERNEL_ERROR（具体数值见
                              #   contracts/cli-contract.md，六类失败两两
                              #   可区分，呼应 spec.md FR-006/SC-006）

pyproject.toml               # 新增 [project.scripts] 条目：
                              # pyh-agent = "platform_service.cli:main"

tests/unit/platform_service/
├── conftest.py                       # 复用既有 fixture（platform_config、
│                                    # stub_provider 等），CLI 测试直接引用
└── test_cli.py                        # 新增：
                                     # - 成功调用（stub provider，捕获 stdout）
                                     # - 未设置 API Key 环境变量 → 失败退出，
                                     #   不构建/不调用 AgentService
                                     # - API Key 不匹配任何租户 → 失败退出
                                     # - 配置文件缺失/无效 → 失败退出
                                     # - 目标问题为空字符串 → 失败退出
                                     # - 内核处理失败（erroring provider）
                                     # - 请求超时（slow provider + 极短超时配置）
                                     # - 会话标识跨两次独立 run() 调用延续上下文
                                     # - tenant_id 贯穿 span（InMemorySpanExporter）
                                     # - 一个基于 subprocess 的最小冒烟测试，
                                     #   验证 console script 确实可执行

examples/demo_cli.py           # 新增：演示脚本（成功/缺少 API Key/身份识别
                              # 失败/内核失败四种场景），复用
                              # examples/platform_config.example.json
```

**Structure Decision**: 不新建独立顶层包——`cli.py` 加入既有 `platform_service`
包，与 `app.py` 并列成为该包内两个平行的"外部形式适配器"，共同依赖同一个
`agent_service.py`/`config.py`/`auth.py`（零改动，不依赖 `scheduler.py`，
见 research.md R3）；完全符合 spec.md FR-003"CLI 复用而非重新实现"的
约束；`pyproject.toml` 新增 console script 声明是唯一的打包层面改动。
