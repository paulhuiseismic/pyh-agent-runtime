---

description: "Task list for message 多渠道收发（消息网关）"
---

# Tasks: message 多渠道收发（消息网关）

**Input**: Design documents from `/specs/009-message-channels/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md；依赖 007（`platform_service.agent_service/app/telemetry`
零改动复用）、008（同属平台层第三个入口，无代码依赖）

**Tests**: 包含测试任务——宪法附加约束要求平台层新增代码附带单元测试。
全部测试均可在无外部网络、无真实模型密钥的情况下运行（内核调用复用
001 已确立的 `httpx.MockTransport` stub 模式；出站回调同样用
`httpx.MockTransport` 构造的"回调记录器" client 驱动；HTTP 层用
`httpx.ASGITransport` 内存直调）。

**Organization**: 按用户故事分组；US1（接入+异步回调）是 MVP 且独立
可测；US2（渠道未识别拒绝 + 重复投递识别）在 US1 建立的接入路径上
补充边界校验；US3（可观测性 + 会话延续）验证与 007/008 一致的遥测/
会话行为。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

不新建顶层包——新增文件落入既有 `src/platform_service/`（新增
`message_gateway.py`，扩展 `config.py`/`errors.py`/`models.py`/`app.py`/
`__init__.py`）与 `tests/unit/platform_service/`（新增
`test_message_gateway.py`/`test_app_messages.py`），见 plan.md
Structure Decision。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 测试公共设施准备（无新增第三方依赖）

- [X] T001 扩展 tests/unit/platform_service/conftest.py：新增
      `channel_config` fixture（`ChannelConfig(channel_id="demo-channel",
      tenant_id="tenant-a", callback_url="http://callback.test/receive")`，
      复用 `platform_config` fixture 所属的 `tenant-a` 租户）；新增
      `recording_callback_client()` 工厂函数——返回一个用
      `httpx.MockTransport` 构造的 `httpx.AsyncClient` 与一个
      `received: list[dict]` 列表（handler 把每次收到的 JSON body
      追加进该列表并返回 200），供后续测试断言出站回调内容

**Checkpoint**: fixture/工厂函数可被后续任务直接 import 使用

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构、异常、数据模型、去重registry——所有用户故事的
共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T002 扩展 src/platform_service/config.py：新增 `ChannelConfig`
      （frozen dataclass：`channel_id`/`tenant_id`/`callback_url` 非空
      校验，`callback_secret: str | None = None`）；`PlatformConfig`
      新增字段 `channels: list[ChannelConfig] = field(default_factory=list)`、
      `callback_timeout_seconds: float = 10.0`、
      `callback_max_retries: int = 3`（后两者 `__post_init__` 校验
      `> 0`；`channels` 校验 `channel_id` 不重复）；`load_config_from_file`
      相应解析 `channels`/`callback_timeout_seconds`/`callback_max_retries`
      （均可选，缺省使用默认值，保持对 007/008 已有配置文件的向后兼容，
      data-model.md）
- [X] T003 [P] 扩展 src/platform_service/errors.py：新增
      `ChannelNotFoundError(channel_id)`（独立于内核异常层级，同
      `AuthenticationError` 等既有平台异常风格）
- [X] T004 [P] 扩展 src/platform_service/models.py：新增 pydantic
      `InboundMessage`（`channel_id`/`external_message_id`/`sender`/
      `text` 非空必填，`conversation_id: str | None = None`）、
      `InboundAcceptResult`（`accepted: bool`, `duplicate: bool`）
- [X] T005 [P] 创建 src/platform_service/message_gateway.py 骨架：
      `ProcessedMessageRegistry` 类——内部 `asyncio.Lock` 保护的
      `set[tuple[str, str]]`；`async def check_and_mark(channel_id,
      external_message_id) -> bool`（锁内原子"查重+标记"，首次见到
      返回 `True`，重复返回 `False`，data-model.md/research.md R4）
- [X] T006 [P] 配置/去重registry 单元测试
      tests/unit/platform_service/test_config.py（扩展）：`ChannelConfig`
      非空字段校验、`channels` 重复 `channel_id` 拒绝、
      `callback_timeout_seconds`/`callback_max_retries` ≤0 拒绝、
      `load_config_from_file` 不提供 `channels` 时默认空列表（向后
      兼容）；tests/unit/platform_service/test_message_gateway.py（新建，
      骨架）：`ProcessedMessageRegistry` 首次调用返回 `True`、重复调用
      返回 `False`、并发调用同一 key 只有一次返回 `True`（用
      `asyncio.gather` 并发调用验证原子性）

**Checkpoint**: `pytest tests/unit/platform_service/test_config.py
tests/unit/platform_service/test_message_gateway.py` 全绿（仅覆盖
本阶段新增部分）

---

## Phase 3: User Story 1 - 外部渠道发来一条消息并异步收到回复 (Priority: P1) 🎯 MVP

**Goal**: 接入请求立即确认（不等待处理完成），后台异步完成 agent 调用
后主动调用渠道配置的出站回调投递结果（成功/内核失败/超时均有明确
反馈）

**Independent Test**: 用 stub provider + 回调记录器驱动
`MessageGateway.handle_inbound()`，验证立即返回的
`InboundAcceptResult(accepted=True, duplicate=False)`；等待后台任务
完成后验证回调记录器收到的 payload 包含正确结果；通过 HTTP 层验证
响应延迟不受慢 provider 影响；用一个恒定失败的回调 client 验证有限次
重试后不向上抛出异常（FR-008）

- [X] T007 [US1] 在 src/platform_service/message_gateway.py 实现
      `MessageGateway` 类与 `build_message_gateway()`：
      `__init__(self, *, agent_service, channels: list[ChannelConfig],
      callback_client, callback_timeout_seconds, callback_max_retries)`
      持有 `self._background_tasks: set[asyncio.Task] = set()`；
      `_resolve_channel(channel_id) -> ChannelConfig`——未匹配抛
      `ChannelNotFoundError`；`async def handle_inbound(message:
      InboundMessage) -> InboundAcceptResult`——1) 解析渠道（异常向上
      抛）；2) `await self._registry.check_and_mark(channel_id,
      external_message_id)` 为 `False` 时直接返回
      `InboundAcceptResult(accepted=True, duplicate=True)`，不调度处理；
      3) 为 `True` 时 `task = asyncio.create_task(self.
      _process_and_callback(message, channel))`，
      `self._background_tasks.add(task)`，
      `task.add_done_callback(self._background_tasks.discard)`，立即
      返回 `InboundAcceptResult(accepted=True, duplicate=False)`（
      research.md R1/R2）；`async def _process_and_callback(message,
      channel)`——用 `platform_request_span(tenant_id=channel.tenant_id,
      session_id=message.conversation_id)` 包裹
      `asyncio.wait_for(self._agent_service.handle(AgentRunRequest(
      goal=message.text, session_id=message.conversation_id),
      tenant_id=channel.tenant_id), timeout=
      self._request_timeout_seconds)`——成功/`asyncio.TimeoutError`/
      其他异常分别构造 status="success"/"timeout"/"kernel_error" 的
      回调 payload（data-model.md），调用
      `send_callback_with_retry(self._callback_client,
      channel.callback_url, payload, timeout=
      self._callback_timeout_seconds, max_retries=
      self._callback_max_retries)`；`async def
      wait_for_background_tasks(self)`——`await asyncio.gather(
      *self._background_tasks)`（测试专用，research.md R2）；模块级
      函数 `async def send_callback_with_retry(client, url, payload,
      *, timeout, max_retries)`——对 `client.post(url, json=payload,
      timeout=timeout)` 做固定间隔的有限次数重试（`max_retries` 次
      尝试），全部失败仅 `logger.warning(...)`，不向调用方抛出
      （research.md R3）；`async def build_message_gateway(config, *,
      agent_service, callback_client=None) -> MessageGateway`——未提供
      `callback_client` 时构造
      `httpx.AsyncClient(timeout=config.callback_timeout_seconds)`
      （生产路径）
- [X] T008 [US1] 扩展 src/platform_service/app.py：lifespan 中
      （`agent_service is None` 分支）额外构建
      `app.state.message_gateway = await build_message_gateway(config,
      agent_service=app.state.agent_service)`；测试注入路径新增
      `message_gateway: MessageGateway | None = None` 参数直接使用；
      新增 `POST /v1/messages/inbound` 端点——请求体由 FastAPI/pydantic
      自动校验 `InboundMessage`（失败自动映射 422）→
      `await message_gateway.handle_inbound(message)` →
      `ChannelNotFoundError` 映射 404 → 成功返回 202
      `InboundAcceptResult`；不改动既有 `/v1/agent/run` 端点的任何行为
      （contracts/message-gateway-api.md）
- [X] T009 [US1] 包级导出 src/platform_service/__init__.py 追加：
      `ChannelConfig`、`InboundMessage`、`InboundAcceptResult`、
      `MessageGateway`、`build_message_gateway`、`ChannelNotFoundError`
- [X] T010 [P] [US1] MessageGateway 端到端单元测试
      tests/unit/platform_service/test_message_gateway.py（扩展）：
      成功场景——stub provider + 回调记录器驱动 `handle_inbound()`，
      验证立即返回 `InboundAcceptResult(accepted=True,
      duplicate=False)`；`await gateway.wait_for_background_tasks()`
      后验证回调记录器收到 `status="success"` 且 `answer` 非空的
      payload（验收场景 US1-2）；内核失败场景（`erroring_provider`）
      验证回调 payload `status="kernel_error"`（验收场景 US1-3）；
      超时场景（`slow_stub_provider` + 极短
      `request_timeout_seconds`）验证回调 payload `status="timeout"`；
      回调投递失败重试耗尽场景（`/speckit-analyze` F1 修正项）——用一个
      每次都返回非 2xx（或抛出异常）的 `httpx.MockTransport` handler
      构造回调 client，并在 handler 内计数被调用次数；驱动一次成功的
      `handle_inbound()`，`await gateway.wait_for_background_tasks()`
      后断言：`send_callback_with_retry` 恰好尝试了
      `config.callback_max_retries` 次（handler 调用计数验证，FR-008）、
      `_process_and_callback()` 全程不向上抛出任何异常（后台任务
      `task.exception()` 为 `None`）、且产生一条 `logger.warning` 记录
      （用 `caplog` 断言日志内容包含"回调"/"failed"等关键字）
- [X] T011 [P] [US1] FastAPI 端到端单元测试
      tests/unit/platform_service/test_app_messages.py（新建）：用
      `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` 驱动
      `POST /v1/messages/inbound`——合法请求立即返回 202 且
      `duplicate=false`（验收场景 US1-1）；用
      `slow_stub_provider`（如 1s 延迟）验证端点响应耗时远小于该延迟
      （SC-001，通过计时断言：`elapsed < 0.5s` 而 provider 延迟为
      `1.0s`）；随后 `await message_gateway.wait_for_background_tasks()`
      验证回调记录器确实收到了结果（验收场景 US1-2）

**Checkpoint**: US1 测试全绿——MVP 可演示（消息接入 → 异步处理 →
出站回调的完整闭环，响应延迟不受处理耗时影响）

---

## Phase 4: User Story 2 - 未配置的渠道请求在触发任何处理前被拒绝 (Priority: P2)

**Goal**: 未配置渠道标识的请求与重复投递均在触发/重复触发内核处理前
被正确处理

**Independent Test**: 向网关投递一条携带未配置渠道标识的消息，验证
立即拒绝且不产生任何出站回调；对同一渠道标识+同一外部消息 ID 投递
两次，验证只触发一次处理与一次回调

- [X] T012 [US2] 在 tests/unit/platform_service/test_message_gateway.py
      补充：`handle_inbound()` 对未配置的 `channel_id` 抛
      `ChannelNotFoundError`，且断言 stub `AgentService`/回调记录器均
      未被调用（验收场景 US2-1）；对同一 `channel_id`+
      `external_message_id` 连续调用两次 `handle_inbound()`，验证
      第二次返回 `duplicate=True`，`wait_for_background_tasks()` 后
      回调记录器只收到一条记录（验收场景 US2-2）
- [X] T013 [P] [US2] 在 tests/unit/platform_service/test_app_messages.py
      补充：`channel_id` 不在配置中的请求返回 404，且响应中不包含
      任何后台处理触发的痕迹（用会在被调用时抛出断言错误的哨兵
      `agent_service` 双重验证）；请求体缺少 `text` 字段返回 422；
      同一渠道+外部消息 ID 的两次 HTTP 投递，第二次响应
      `duplicate=true` 且回调记录器只收到一次回调

**Checkpoint**: US1+US2 测试全绿——渠道校验与重复投递识别均在到达
`AgentService` 之前生效

---

## Phase 5: User Story 3 - 消息处理与 007/008 保持一致的可观测性与会话延续 (Priority: P3)

**Goal**: 每条消息触发的内核可观测记录携带一致租户标识；共享同一对话
标识的多条消息延续此前积累的上下文

**Independent Test**: 用 in-memory span exporter 驱动一次成功处理，
验证 `platform.request` 根 span 与其下内核子 span 均携带一致
`tenant_id`；连续投递两条共享 `conversation_id` 的消息，验证第二条的
回调 `answer` 体现第一条积累的上下文

- [X] T014 [P] [US3] 创建 tests/unit/platform_service/test_message_gateway_telemetry.py：
      用 `InMemorySpanExporter` 驱动 `handle_inbound()` 的成功场景，
      `await gateway.wait_for_background_tasks()` 后断言
      `platform.request` span 携带正确 `tenant_id`，其下 `react.step`/
      `chat {model}` 子 span 与之 trace_id 一致、父子关系正确（复用
      007/008 已确立的断言风格，验收场景 US3-2）
- [X] T015 [P] [US3] 在 tests/unit/platform_service/test_message_gateway.py
      补充：连续两次调用 `handle_inbound()`（相同 `channel_id`+
      `conversation_id`、不同 `external_message_id`），每次调用后
      `await wait_for_background_tasks()`，验证第二次回调记录器收到
      的 `answer` 体现第一次消息积累的会话上下文（复用 stub provider
      按调用次数返回不同内容的模式，验收场景 US3-1）

**Checkpoint**: US1-US3 测试全绿——消息网关的调用、边界校验、可观测性
与会话延续全部具备，与 007/008 行为一致

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 演示脚本、示例配置、文档收尾与最终验证

- [ ] T016 [P] 扩展 examples/platform_config.example.json：新增
      `channels`（至少一个渠道实例）、`callback_timeout_seconds`、
      `callback_max_retries` 字段示例
- [ ] T017 [P] 创建演示脚本 examples/demo_message_gateway.py：复用
      T016 的示例配置结构（provider 替换为 stub，出站回调替换为回调
      记录器，避免需要真实网络），依次演示成功投递+异步回调、渠道
      未识别、重复投递、内核失败四个场景，打印每个场景的接入响应与
      （如适用）收到的回调 payload
- [ ] T018 按 quickstart.md 全流程验证：
      `pytest tests/unit/platform_service -v` 全绿（含新增的
      `test_message_gateway.py`/`test_app_messages.py`/
      `test_message_gateway_telemetry.py`）→ demo 脚本输出符合预期 →
      修复发现的问题
- [ ] T019 更新 README.md roadmap：009 状态改为"✅ 已完成"；更新
      examples/README.md 追加 `demo_message_gateway.py` 条目

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：依赖 Phase 2 全部任务，是 US2/US3 的基础
  （`MessageGateway`/`app.py` 端点均在 US1 建立）
- **US2**：依赖 US1 已建立的 `handle_inbound()`/端点（本阶段不修改
  已有控制流，只补充边界场景的验证）
- **US3**：依赖 US1 建立的 `_process_and_callback()` 主流程（遥测/
  会话延续均已随 T007 一并实现，本阶段补充验证）
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T003/T004/T005/T006 可并行（T002 先行，T006 依赖
  T002/T005 的类型定义）
- US1 内：T010/T011 可并行编写（不同文件）
- US2 内：T012/T013 可并行编写（不同文件）
- US3 内：T014/T015 可并行编写（不同文件）
- Phase 6：T016/T017 可并行；T018 依赖 T017；T019 依赖 T018

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T011）：消息接入 → 异步处理 → 出站
回调的完整闭环即可演示核心价值（含超时/内核失败的回调反馈），完全
不需要渠道边界校验的专项测试或遥测/会话延续的专项验证。随后 US2
（渠道未识别 + 重复投递）→ US3（可观测性 + 会话延续）递增交付，最后
Polish 补齐示例配置、演示脚本与文档。每个 Checkpoint 处 `pytest`
必须全绿再前进。
