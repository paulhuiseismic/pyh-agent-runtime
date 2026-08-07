# Implementation Plan: message 多渠道收发（消息网关）

**Branch**: `009-message-channels` | **Date**: 2026-08-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-message-channels/spec.md`

## Summary

在既有 `src/platform_service/` 包内新增第三个对外入口——消息网关
（`message_gateway.py` + `app.py` 新增的 `POST /v1/messages/inbound`
路由），与 007（REST，同步阻塞）、008（CLI，单次执行）并列，但采用
不同的交互模型：接入请求立即确认（不等待处理完成），处理在独立的
`asyncio.Task` 中异步完成后，主动调用该消息所属渠道配置的出站回调
地址投递结果。核心处理逻辑（租户识别、`AgentService` 调用、遥测 span）
与 007/008 完全复用，零改动；新增的只是「消息接入 → 去重 → 异步调度 →
出站回调（含有限重试）」这一层胶水代码，以及为此新增的 `PlatformConfig`
配置项（`channels`/`callback_timeout_seconds`/`callback_max_retries`，
延续 007 `mcp_servers` 的"默认空列表、按需启用"风格）。

## Technical Context

**Language/Version**: Python 3.12（延续 001-008）

**Primary Dependencies**: 无新增第三方依赖——复用已有的 `fastapi`
（新增路由）、`httpx`（出站回调用一个独立的 `httpx.AsyncClient`，与
001 `LLMProvider` 内部管理 httpx 客户端的方式一致）；不引入任何消息
队列/任务调度第三方库（研究阶段评估后判定用标准库 `asyncio.create_task`
即可满足"异步处理 + 有限重试"的最简实现，见 research.md R1）

**Storage**: 复用 003/004 已交付的 `SqliteMemory`/`LongTermMemory`
（经由 `AgentService` 间接复用，会话标识 = 渠道消息的对话标识）；新增
的"已处理消息去重记录"为进程内存状态（`set`，见 research.md R4），
不新增数据库表

**Testing**: pytest + pytest-asyncio；HTTP 层测试延续 007/008 的
`httpx.ASGITransport`（内存直调 FastAPI app，不监听真实端口）；出站
回调测试用 `httpx.MockTransport` 构造用于回调的 `httpx.AsyncClient`
（与 001 stub provider 同一模式）；后台任务的完成时机通过
`MessageGateway` 暴露的测试专用等待方法同步（research.md R2），不依赖
真实 sleep 或轮询

**Target Platform**: 同 001-008（Linux server 生产 / Windows 本地开发）

**Project Type**: web service 扩展（在既有 007 `platform_service` 平台
层包内新增第三个入口，不新建独立顶层包）

**Performance Goals**: 不设精确基准，同 007/008；接入请求的响应延迟
MUST NOT 受后台 agent 处理耗时影响（SC-001），处理耗时上限复用
`PlatformConfig.request_timeout_seconds`（不新增重复的超时配置项）

**Constraints**: MUST NOT 修改 007/008 已冻结的 `AgentService`/
`PlatformConfig` 既有字段行为、`resolve_tenant`/`build_agent_service`
签名（spec.md FR-003，只做新增字段的兼容式扩展）；出站回调这一外部
HTTP 调用 MUST 设置显式超时且重试次数 MUST 有限（呼应宪法原则 IV，
FR-008）；去重记录、渠道-租户映射均不追求跨进程强一致性（与 007/008
已有假设一致）

**Scale/Scope**: 2 个新源文件（`message_gateway.py`、扩展
`config.py`/`errors.py`/`models.py`/`app.py`/`__init__.py`）+ 单元测试
（含出站回调重试测试）+ 一个演示脚本；不涉及具体渠道厂商 API 对接、
不涉及消息队列/持久化重试基础设施、不涉及渠道配置管理界面

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | `message_gateway.py` 与 `agent_service.py`/`app.py` 一样只单向 import `kernel.*`/`platform_service.*`；内核代码零改动 | ✅ 通过 |
| II. 最简实现 | 异步处理用标准库 `asyncio.create_task`，不引入消息队列/任务调度第三方库；去重用进程内存 `set`，不引入外部缓存；出站回调重试用固定次数 + 固定间隔，不引入指数退避框架（research.md R1/R3/R4，均为按需最简选择） | ✅ 通过 |
| III. 组装优先 | 无新增第三方依赖，无需更新 THIRD_PARTY.md | ✅ 通过 |
| IV. 超时与成本上限 | 出站回调这一外部 HTTP 调用设置显式 `callback_timeout_seconds`（新增可配置项，无"无限制"默认值）；重试次数为显式 `callback_max_retries`（有限，非无限重试）；后台处理复用既有 `request_timeout_seconds` | ✅ 通过 |
| V. OTel GenAI 可观测 | 复用 `platform_request_span`（零改动），每条消息触发的处理沿用与 007/008 完全一致的 span 结构与 `tenant_id` 贯穿（FR-009/SC-006） | ✅ 通过 |
| VI. 测试与安全边界 | `message_gateway.py` 属于平台层胶水代码，按宪法附加约束补充单元测试（覆盖成功/渠道未识别/重复投递/超时/内核失败/回调重试耗尽）；后台任务生命周期由 `MessageGateway` 持有强引用管理，不引入无界并发（有多少条消息就有多少个受控的后台任务，无循环重试之外的无界行为） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入任何新依赖，`PlatformConfig`
新增字段均为可选（默认空列表/安全默认值），不影响 007/008 已有配置的
向后兼容性，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/009-message-channels/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── message-gateway-api.md   # 入站接入契约 + 出站回调契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/platform_service/
├── config.py（扩展）        # 新增 ChannelConfig（frozen dataclass：
│                           # channel_id/tenant_id/callback_url/
│                           # callback_secret，channel_id 非空、不重复）；
│                           # PlatformConfig 新增字段：
│                           # channels: list[ChannelConfig] = []（默认
│                           # 空，未配置渠道时网关拒绝一切投递，与 007
│                           # mcp_servers 的默认空列表风格一致）、
│                           # callback_timeout_seconds: float = 10.0、
│                           # callback_max_retries: int = 3（均校验 > 0）；
│                           # load_config_from_file 相应解析 channels 字段
├── errors.py（扩展）        # 新增 ChannelNotFoundError(channel_id)
├── models.py（扩展）        # 新增 InboundMessage（pydantic：channel_id/
│                           # external_message_id/text 非空必填，sender
│                           # 必填，conversation_id 可选）；
│                           # InboundAcceptResult（accepted: bool,
│                           # duplicate: bool）供接入端点返回
├── message_gateway.py（新增） # ProcessedMessageRegistry：asyncio.Lock
│                           # 保护的 set[(channel_id, external_message_id)]，
│                           # `check_and_mark()` 原子"查重+标记"（同
│                           # scheduler.py try_acquire 的原子性写法）；
│                           # MessageGateway 类：`handle_inbound(message)`
│                           # ——解析渠道（ChannelNotFoundError 向上抛）→
│                           # 查重（重复则返回 duplicate=True，不调度
│                           # 处理）→ 标记已处理 → `asyncio.create_task`
│                           # 调度后台处理（任务引用存入
│                           # `self._background_tasks: set`，完成时自动
│                           # discard，避免被 GC）→ 立即返回
│                           # `InboundAcceptResult(accepted=True,
│                           # duplicate=False)`；后台方法
│                           # `_process_and_callback(message, channel)`——
│                           # 用 `platform_request_span` 包裹
│                           # `asyncio.wait_for(agent_service.handle(...),
│                           # timeout=config.request_timeout_seconds)`，
│                           # 成功/超时/内核失败分别构造出站回调 payload，
│                           # 调用 `send_callback_with_retry`；
│                           # `send_callback_with_retry(client, url,
│                           # payload, *, timeout, max_retries)`——对
│                           # `httpx.AsyncClient.post` 做固定间隔的有限
│                           # 次数重试，全部失败仅记录日志（不向调用方
│                           # 传播，回调投递失败不应影响进程本身）；
│                           # `build_message_gateway(config, *,
│                           # agent_service, callback_client=None)`——
│                           # 生产路径按 config 构造共享的
│                           # `httpx.AsyncClient(timeout=
│                           # callback_timeout_seconds)`，测试可注入
│                           # `callback_client`（MockTransport 驱动）；
│                           # 暴露 `async def wait_for_background_tasks()`
│                           # 测试专用方法，确定性等待所有已调度的后台
│                           # 任务完成（research.md R2）
├── app.py（扩展）           # lifespan 中额外构建
│                           # `app.state.message_gateway =
│                           # await build_message_gateway(config,
│                           # agent_service=app.state.agent_service)`；
│                           # 新增 `POST /v1/messages/inbound` 端点：
│                           # 请求体由 FastAPI/pydantic 自动校验
│                           # `InboundMessage`（失败自动映射 422）→
│                           # `await message_gateway.handle_inbound(...)`
│                           # → `ChannelNotFoundError` 映射 404 → 成功
│                           # 返回 202 Accepted（`InboundAcceptResult`）；
│                           # 不改动既有 `/v1/agent/run` 端点的任何行为
└── __init__.py（扩展）      # 追加导出 ChannelConfig、InboundMessage、
                            # MessageGateway、build_message_gateway、
                            # ChannelNotFoundError

tests/unit/platform_service/
├── conftest.py（扩展）      # 新增：至少一个 ChannelConfig fixture、
│                           # 一个用 httpx.MockTransport 构造的"回调
│                           # 记录器" client（记录每次收到的回调 payload，
│                           # 供断言）
├── test_config.py（扩展）   # ChannelConfig/新增 PlatformConfig 字段的
│                           # 校验用例
├── test_message_gateway.py（新增） # MessageGateway 端到端组合测试
│                           # （不经过 HTTP）：成功/渠道未识别/重复投递/
│                           # 超时/内核失败/回调失败重试耗尽仍不抛出
└── test_app_messages.py（新增）    # FastAPI 端到端（httpx.ASGITransport）：
                            # POST /v1/messages/inbound 的成功接入/
                            # 未知渠道 404/参数校验 422/会话延续/
                            # tenant_id 贯穿 span

examples/demo_message_gateway.py（新增） # 演示：成功投递+异步回调、
                                        # 渠道未识别、重复投递、内核失败
examples/platform_config.example.json（扩展） # 新增 channels 字段示例
```

**Structure Decision**: 不新建独立顶层包——`message_gateway.py` 加入
既有 `platform_service` 包，与 `agent_service.py` 并列成为"处理逻辑"层
（`app.py` 只做 HTTP 适配，不下沉业务逻辑，延续 007/008 已确立的分工）；
`PlatformConfig` 只做新增字段的向后兼容扩展，不改变任何既有字段的语义。
