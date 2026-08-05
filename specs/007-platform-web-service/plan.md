# Implementation Plan: 平台服务层 + web service（REST API）

**Branch**: `007-platform-web-service` | **Date**: 2026-08-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-platform-web-service/spec.md`

## Summary

新增第一个平台层 Python 包 `src/platform_service/`（内核 `kernel` 之外的独立包，
依赖方向单向指向内核，符合宪法原则 I）。核心是一个 `AgentService`（`agent_service.py`）
——把 001 `LLMProvider`、002 `ReactEngine`、003 会话记忆、004 长期记忆、005/006
`ToolRegistry`（含沙箱工具与 MCP 工具）组合成"处理一次 Agent 调用请求"的完整
路径，这条路径本身不感知调用方是 REST 还是未来的 CLI（008），只被一层极薄的
`app.py`（FastAPI）适配为 REST 接口。租户识别（静态 API Key → 租户映射）、
并发调度（per-tenant + 全局计数器，超限立即拒绝）、请求级超时均在 `AgentService`
被调用之前/之外的独立模块完成，不侵入内核代码。

## Technical Context

**Language/Version**: Python 3.12（延续 001-006）

**Primary Dependencies**: 新增 `fastapi`（MIT，经用户确认引入）、`uvicorn`
（MIT，已因 006 安装 `mcp` SDK 而存在于依赖树中，本 feature 将其提升为直接
依赖，用于运行 ASGI 应用）；复用现有 `httpx`/`opentelemetry-api`/`opentelemetry-sdk`/
`aiosqlite`/`mcp`

**Storage**: 复用 003 已交付的 `SqliteMemory`（会话历史）与 004 的
`LongTermMemory`（跨会话事实）；新增的租户配置（API Key → 租户标识、
per-tenant 并发上限）为进程内存中的配置对象，从启动时加载的配置文件读取，
不新增数据库表

**Testing**: pytest + pytest-asyncio；HTTP 层测试用 FastAPI 官方推荐的
`httpx.ASGITransport`（内存中直接调用 ASGI app，不监听真实端口，无网络
依赖）；内核调用继续复用 001 已确立的 `httpx.MockTransport` stub 模式，
不需要真实模型或真实 MCP server

**Target Platform**: 同 001-006（Linux server 生产 / Windows 本地开发）

**Project Type**: web service（内核之外新增的第一个平台层包，单进程部署，
无前后端分离）

**Performance Goals**: 不设精确基准测试任务，同 001-006 的处理方式；并发
调度以进程内计数器实现，量级面向"单进程多租户"场景，不面向多实例横向扩展
（多实例场景的调度一致性留给未来 010 按需评估）

**Constraints**: 不修改 001-006 已冻结的任何内核接口（`Tool` Protocol、
`ReactEngine`、`SqliteMemory`/`LongTermMemory`、`ToolRegistry` 签名一律不变）；
`AgentService` 的处理路径 MUST 可被非 REST 调用方（未来 CLI）直接复用，
MUST NOT 把路由/租户识别/调度逻辑写死在 `app.py` 里（FR-003/SC-006）；
请求整体处理超时、并发上限均不允许配置为"无限制"（呼应宪法原则 IV）

**Scale/Scope**: 约 8-9 个源文件（配置/错误/鉴权/调度/AgentService/models/
FastAPI app/telemetry）+ 单元测试 + 一份最小配置文件示例；不涉及 CLI（008）、
不涉及租户配置管理界面/审计报表（010）、不涉及多实例部署一致性

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | `platform_service` 是内核之外的新包，只单向 import `kernel.*`；内核代码零改动、零新增对平台层的感知 | ✅ 通过 |
| II. 最简实现 | 用 FastAPI 现成的路由/请求校验能力，不自研 Web 框架；`AgentService` 只做"组合内核能力"的胶水代码，不引入未讨论的抽象（如插件式中间件系统） | ✅ 通过 |
| III. 组装优先 | 新增依赖 `fastapi`（MIT）已经用户确认，将登记 THIRD_PARTY.md；`uvicorn` 已在依赖树中，此处提升为直接依赖同样登记；不 fork 任何第三方源码 | ✅ 通过 |
| IV. 超时与成本上限 | 请求整体处理设置显式超时（FR-009），内核内部各项调用超时延续 001-006 已有约束；并发上限（per-tenant + 全局）均要求正整数配置，不允许"无限制" | ✅ 通过 |
| V. OTel GenAI 可观测 | 租户标识从 API Key 解析后贯穿传入 `AgentService` 触发的每一次内核调用（FR-006）；新增 `platform.request` 请求级 span 同样携带 tenant_id，便于从平台入口到内核调用的全链路追踪 | ✅ 通过 |
| VI. 测试与安全边界 | 新增模块（鉴权/调度/AgentService/FastAPI app）均有单元测试；`AgentService` 调用 `ReactEngine.run()` 时的 `max_steps` 由平台配置提供合法正整数，不引入无界循环 | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物新增的唯一直接依赖是 `fastapi`（`uvicorn`
从传递依赖提升为直接依赖），均已在 Phase 0 前经用户确认，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/007-platform-web-service/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── agent-run-api.md  # 对外 REST 接口契约 + AgentService 内部契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/platform_service/
├── __init__.py             # 包级导出：AgentService、app（FastAPI 实例）等
├── config.py               # TenantConfig（api_key→tenant_id、per-tenant 并发上限）、
│                           # PlatformConfig（全局并发上限、请求超时、model/max_steps、
│                           # provider_base_url/provider_api_key/price_table/
│                           # provider_call_limits——001 LLMProvider 的构造依据，
│                           # FR-013/FR-014、mcp_servers——可选 MCP 接入列表，默认空），
│                           # 从配置文件加载；provider 配置缺失/无效时构造即抛异常
│                           # （启动期失败，不允许"运行中但请求必然失败"）
├── errors.py                # 平台层异常：AuthenticationError、
│                           # ConcurrencyLimitExceededError、RequestTimeoutError
│                           # （均独立于内核异常层级，供 app.py 映射为 HTTP 状态码）
├── auth.py                  # resolve_tenant(api_key) -> tenant_id；
│                           # 未匹配到租户抛 AuthenticationError
├── scheduler.py              # ConcurrencyScheduler：per-tenant 计数器 + 全局计数器，
│                           # try_acquire(tenant_id)/release(tenant_id)，超限立即抛
│                           # ConcurrencyLimitExceededError（不排队，FR-012）
├── models.py                 # AgentRunRequest/AgentRunResult（pydantic，同时用作
│                           # FastAPI 请求/响应 schema 与 AgentService 的输入输出类型）
├── agent_service.py           # AgentService：组合 001 LLMProvider + 002 ReactEngine +
│                           # 003 SqliteMemory + 004 LongTermMemory + 005/006
│                           # ToolRegistry，处理一次 AgentRunRequest → AgentRunResult；
│                           # 是 REST 与未来 CLI 共用的核心路径（FR-003/SC-006）；
│                           # 内含 SessionLockRegistry（按 session_id 惰性创建
│                           # asyncio.Lock，串行化同一会话的并发请求，不同会话
│                           # 互不阻塞，FR-015）
├── telemetry.py               # platform.request span（tenant_id/api 请求级观测），
│                           # 复用 kernel.provider 的 tracer
└── app.py                     # FastAPI 应用：单一 POST 端点，读取 API Key 请求头 →
                              # auth.resolve_tenant → scheduler.try_acquire →
                              # asyncio.wait_for(agent_service.handle(...), timeout=
                              # PlatformConfig.request_timeout_seconds) →
                              # 映射各类失败为对应 HTTP 状态码

tests/unit/platform_service/
├── conftest.py                       # PlatformConfig/TenantConfig 测试 fixture、
│                                    # stub LLMProvider（复用 001 MockTransport 模式）
├── test_config.py                     # 配置加载与校验（超时/并发上限非法值拒绝）
├── test_auth.py                       # API Key → 租户解析成功/失败
├── test_scheduler.py                   # per-tenant/全局并发上限立即拒绝、
│                                    # 一个租户超限不影响另一租户
├── test_agent_service.py               # AgentService 端到端组合调用（stub provider，
│                                    # 会话记忆读写、工具调用）、内核失败透传
└── test_app.py                        # FastAPI 端到端（httpx.ASGITransport）：
                                     # 成功调用、鉴权失败、并发超限、参数校验失败、
                                     # 内核失败、请求超时，六类响应可区分（FR-007）
```

**Structure Decision**: 新增独立顶层包 `platform_service`（避免与标准库
`platform` 模块同名冲突），内部按职责单文件拆分（配置/异常/鉴权/调度/
数据模型/核心服务/遥测/REST 适配各一个文件），延续 001-006 的扁平单包
布局风格；`agent_service.py` 是唯一被 REST（`app.py`）与未来 CLI（008）
共同依赖的模块，`app.py` 本身只做"HTTP ↔ AgentService"的薄适配，不下沉
任何业务逻辑，满足 FR-003/SC-006 对"处理路径与对外接口形式解耦"的要求。
