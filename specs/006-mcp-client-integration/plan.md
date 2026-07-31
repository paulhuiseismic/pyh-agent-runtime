# Implementation Plan: MCP 客户端接入

**Branch**: `006-mcp-client-integration` | **Date**: 2026-07-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-mcp-client-integration/spec.md`

## Summary

在 `src/kernel/tool/` 中新增 MCP 客户端子模块：`McpServerConfig`（stdio 命令 / HTTP
地址 + 各阶段超时配置）、`McpServerConnection`（基于官方 MCP Python SDK 完成握手、
`tools/list` 发现、`tools/call` 调用，stdio 与 HTTP 两种传输共用同一套上层接口）、
`McpTool`（实现 001 冻结的 `Tool` Protocol，把一个已发现的 MCP 工具适配为可被
`ToolRegistry`（005）注册、被 `ReactEngine`（002）直接调用的对象）。协议层的
JSON-RPC 握手/帧/能力协商全部委托给官方 SDK（宪法原则 III：组装优先于自研），
本 feature 只负责：连接生命周期管理、超时包裹（宪法原则 IV）、错误分类
（连接失败/超时/连接中断/业务失败）、以及与已有 Tool/ToolRegistry 体系的适配。

## Technical Context

**Language/Version**: Python 3.12（延续 001-005）

**Primary Dependencies**: 新增 `mcp`（官方 Model Context Protocol Python SDK，MIT
license，已经用户确认引入）；其余复用现有依赖——`opentelemetry-api`/`-sdk`（span）、
标准库 `asyncio`（超时包裹、任务生命周期）

**Storage**: N/A（本 feature 无持久化；连接状态与已发现工具只保存在内存中）

**Testing**: pytest + pytest-asyncio；stdio 传输用真实子进程运行一个基于 SDK
`FastMCP` 编写的测试用 server 脚本（`tests/unit/tool/mcp_fixtures/stdio_server.py`）
做端到端集成测试；HTTP 传输用同进程内以 `FastMCP` streamable-http 模式启动的
后台测试 server（测试内启停，不依赖外部网络）；连接失败/超时/中断三类失败场景
用不存在的命令 / 刻意阻塞的测试 server 工具 / 测试中途关闭 server 进程模拟

**Target Platform**: 同 001-005（Linux server 生产 / Windows 本地开发）；stdio
子进程与超时机制在两平台行为一致，无需像 005 那样区分 POSIX-only 能力

**Project Type**: library（内核 tool 子模块的扩展，新增 MCP 客户端能力，不改动
005 已冻结的 `ToolRegistry`/`SandboxedTool` 行为）

**Performance Goals**: 连接建立 + 工具发现（≤20 个工具）在正常条件下数秒内完成
（对应 spec SC-002）；不设精确基准测试任务，同 001-005 的处理方式

**Constraints**: 不改变 001/002 冻结的 `Tool` Protocol 签名（FR-005）；每个连接
配置的超时（握手/发现/调用）不允许配置为"无限制"（呼应宪法原则 IV）；发现的
工具与已注册工具重名时必须走 005 `ToolRegistry` 既有的拒绝逻辑，不新增覆盖语义
（FR-006）；单个 MCP 连接的失败不得影响其他工具（本地/沙箱/其他 MCP 连接）的
可用性（FR-009）

**Scale/Scope**: 约 5-6 个源文件 + 测试用 fixture server 脚本 + 单元/集成测试；
不涉及 MCP 规范中的 resources/prompts 能力、不涉及自动重连、不涉及平台层

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | MCP 客户端子模块位于 `kernel/tool/` 内，零 import 平台层；`McpServerConnection`/`McpTool` 均为纯内核实现 | ✅ 通过 |
| II. 最简实现 | 协议细节（握手/帧/能力协商）全部委托官方 SDK，不自行解析 JSON-RPC；本 feature 只写连接编排与适配层 | ✅ 通过 |
| III. 组装优先 | 新增依赖为官方 MCP Python SDK（MIT），经用户确认后引入，登记于 THIRD_PARTY.md；不 fork/修改其源码 | ✅ 通过 |
| IV. 超时与成本上限 | 握手/工具发现/工具调用三个阶段各自显式超时，禁止"无限制"配置（FR-007） | ✅ 通过 |
| V. OTel GenAI 可观测 | 每次连接生命周期事件（连接/断开/连接失败）与每次工具调用发 span，含 tenant_id（FR-010），复用 005 建立的 `tool.invoke` span 命名与属性约定 | ✅ 通过 |
| VI. 测试与安全边界 | 三类失败场景（连接失败/超时/中断）均有单测；已注册工具重名冲突有单测；MCP 连接失败不影响其他工具的单测（FR-009 对应） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物新增的唯一依赖（`mcp` SDK）已在 Phase 0 阶段
经用户确认并将登记到 THIRD_PARTY.md，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/006-mcp-client-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── mcp-tool-adapter-api.md  # 对上层（ToolRegistry/ReactEngine）暴露的接口契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/kernel/tool/
├── __init__.py            # 扩展导出：McpServerConfig、McpServerConnection、
│                           # McpTool、MCP 异常层级（保留 005 已有导出不变）
├── mcp_models.py           # McpServerConfig（stdio 命令 / HTTP 地址 + 超时，
│                           # frozen dataclass，安全默认值）、
│                           # McpConnectionState 枚举、DiscoveredMcpTool
├── mcp_errors.py            # McpError 基类 → McpConnectionError（连接/握手失败）、
│                           # McpTimeoutError（任一阶段超时）、
│                           # McpDisconnectedError（调用中途连接断开）；
│                           # McpToolExecutionError（工具执行业务失败，与 005
│                           # SandboxToolExecutionError 同级语义）
├── mcp_client.py            # McpServerConnection：connect()/discover_tools()/
│                           # call_tool()/disconnect()，内部持有官方 SDK 的
│                           # ClientSession，stdio/HTTP 两种传输通过同一接口暴露
├── mcp_tool.py              # McpTool：实现 Tool Protocol，invoke() 转调
│                           # McpServerConnection.call_tool()，转换调用结果为
│                           # 字符串；提供 register_mcp_tools() 辅助函数：
│                           # 发现 + 适配 + 注册进 ToolRegistry，重名交由
│                           # ToolRegistry.register() 原生拒绝
└── telemetry.py             # 扩展（复用 005 已有文件）：新增
                            # mcp_connection_span()，tool.invoke span 复用不变

tests/unit/tool/
├── mcp_fixtures/
│   └── stdio_server.py                 # 基于 FastMCP 的测试用 MCP server：
│                                        # 暴露 echo/slow/fail 三个测试工具，
│                                        # 通过 stdio 与 HTTP 两种模式均可启动
├── conftest.py（扩展）                    # MCP server 命令/地址 fixture、
│                                        # McpServerConfig fixture
├── test_mcp_models.py                    # McpServerConfig 校验（超时非法值拒绝）
├── test_mcp_connect_discover.py           # US1：stdio 握手 + tools/list 发现
├── test_mcp_http_transport.py             # US2：HTTP 传输握手/发现/调用，
│                                        # 与 stdio 场景行为等价
├── test_mcp_tool_invoke.py                # US1：McpTool.invoke() 透传调用与
│                                        # 结果转换；与 ToolRegistry 集成注册
├── test_mcp_registry_conflict.py           # FR-006：发现工具与已注册工具重名
│                                        # 时注册被拒绝，不覆盖已注册工具
├── test_mcp_failure_isolation.py           # US3：连接失败/超时/中途断连三类
│                                        # 场景，及"单个连接失败不影响其他
│                                        # 已注册工具"（FR-009）
└── test_mcp_telemetry.py                   # 连接生命周期与调用 span 属性、
                                        # 遥测容错（复用 005 BrokenTracer 模式）
```

**Structure Decision**: 延续 005 的扁平文件布局，在既有 `kernel/tool/` 包内按
`mcp_` 前缀新增文件，不引入独立子包，与 005 的 `sandbox_*` 命名风格保持一致；
`ToolRegistry`/`Tool` Protocol/`telemetry.py` 的现有文件与导出不变，MCP 相关能力
以"新增文件 + 扩展 `__init__.py` 导出"的方式接入，符合宪法原则 II（最简实现，
不重构已冻结的 005 接口）。
