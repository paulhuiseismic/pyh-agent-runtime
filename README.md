# pyh-agent-runtime

多租户企业级 agent runtime 底座。

治理规则见 [宪法](.specify/memory/constitution.md)（v1.0.0），开发流程走
Spec Kit：`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`。

## 五大核心能力

1. **provider** — LLM 对接与多模型路由（经 LiteLLM proxy）
2. **react** — ReAct 引擎（循环编排、最大步数限制）
3. **memory** — memory 压缩与上下文管理
4. **plugin tool + sandbox** — 工具插件机制与沙箱执行
5. **web service** — 本项目对外的 REST 服务（调用入口、调度、多租户、审计）

五大能力的对外服务同时支持 **CLI** 与 **WEB（REST）** 两个入口；
两个入口共享同一平台服务层，仅作为薄适配器存在，保证行为一致。

## 分层架构

```text
┌─────────────────────────────────────────────┐
│  平台层（web service）                        │
│  · REST API：agent 调用入口、会话/租户管理     │
│  · message 网关：多渠道接入/发送适配           │
│  · 调度器：agent 运行调度、并发控制            │
│  · 多租户：租户识别、配额、隔离                │
│  · 审计：审计与成本核算（消费 OTel/Langfuse）   │
└──────────────────┬──────────────────────────┘
                   │ 依赖方向：只允许 平台 → 内核
┌──────────────────▼──────────────────────────┐
│  内核（可独立测试，不感知平台）                 │
│  · provider ─ LLM 调用（超时/token/成本上限）  │
│  · react    ─ ReAct 循环（最大步数）           │
│  · memory   ─ 上下文管理与压缩                 │
│  · tool     ─ 工具注册与执行（沙箱在其后）      │
└─────────────────────────────────────────────┘
```

强制约束（宪法摘要）：内核不依赖平台层；所有外部调用显式超时；LLM 调用带
token 与成本上限；所有 LLM 调用/tool 执行/消息进出发出 OTel GenAI span 且
必带 `tenant_id`；第三方组件仅经网络 API 集成，license 登记于
[THIRD_PARTY.md](THIRD_PARTY.md)。

## Feature Roadmap

| # | Feature | 层 | 状态 |
|---|---------|-----|------|
| 001 | [内核骨架 + provider](specs/001-kernel-provider/spec.md) | 内核 | ✅ 已完成 |
| 002 | [ReAct 引擎](specs/002-react-engine/spec.md) | 内核 | ✅ 已完成 |
| 003 | [memory 压缩与上下文管理](specs/003-memory-compression/spec.md) | 内核 | ✅ 已完成 |
| 004 | [长期记忆（跨会话 profile/fact 存储与查询）](specs/004-long-term-memory/spec.md) | 内核 | ✅ 已完成 |
| 005 | [plugin tool 插件机制 + sandbox](specs/005-tool-plugin-sandbox/spec.md) | 内核 + 执行环境 | ✅ 已完成 |
| 006 | [MCP 客户端接入（stdio/HTTP 传输、工具发现、适配为 Tool Protocol）](specs/006-mcp-client-integration/spec.md) | 内核 | ✅ 已完成 |
| 007 | [平台服务层 + web service（REST API）+ 运行调度](specs/007-platform-web-service/spec.md) | 平台 | ✅ 已完成 |
| 008 | CLI 入口（复用平台服务层） | 平台 | 待 specify |
| 009 | message 多渠道收发 | 平台 | 待 specify |
| 010 | 多租户强化与审计 | 平台 | 待 specify |

## 技术基线

- 内核：Python 3.12 + httpx + OpenTelemetry SDK；测试 pytest（stub 化，零外部依赖）
- 模型路由：LiteLLM proxy（独立部署，OpenAI 兼容 HTTP，MIT 核心功能）
- 可观测：OTel GenAI 语义约定 → Langfuse（平台层接入）
- 存储：内核只定义接口，实现由平台注入；MVP 默认 SQLite（WAL，
  `aiosqlite` 异步驱动，003 已落地于 memory 模块），多实例部署时迁 PostgreSQL
