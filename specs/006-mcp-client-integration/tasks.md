---

description: "Task list for MCP 客户端接入"
---

# Tasks: MCP 客户端接入

**Input**: Design documents from `/specs/006-mcp-client-integration/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`Tool` Protocol、`InvalidRequestError` 已交付）、002（`ReactEngine` 兼容性验证）、
005（`ToolRegistry` 已冻结的重名拒绝行为、`tool.invoke` span 命名与属性约定）

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试，不适用模板的
"测试可选"约定。全部测试均可在无外部网络的情况下运行（stdio/HTTP 两种传输的测试
对端均由测试自身用官方 SDK `FastMCP` 在本机启动）。

**Organization**: 按用户故事分组；US1（stdio 连接/发现/适配/调用）是 MVP 且独立可测；
US2（HTTP 传输）在 US1 建立的 `McpServerConnection` 上补一个传输分支，行为对上层
透明；US3（失败隔离）在 US1/US2 已建立的连接/调用路径上补全三类失败的分类与隔离。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

延续 001-005 的单包 library 布局：`src/kernel/tool/`、`tests/unit/tool/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 引入新依赖、登记 license、准备测试用 MCP server fixture

- [X] T001 在 pyproject.toml 的 `dependencies` 中新增 `mcp`（官方 Model Context
      Protocol Python SDK），并在 THIRD_PARTY.md 追加一行登记（组件名/MIT
      license/Python 库依赖/无特殊约束），随后执行 `pip install -e ".[dev]"`
      验证安装成功、`python -c "import mcp"` 可正常导入（research.md R1）
- [X] T002 [P] 创建测试用 MCP server tests/unit/tool/mcp_fixtures/test_server.py：
      基于 `mcp.server.fastmcp.FastMCP` 定义 3 个工具——`echo`（原样返回入参
      字典）、`slow`（`await asyncio.sleep(seconds)`，seconds 由入参指定，用于
      触发调用超时）、`fail`（显式返回 `isError=True` 的结果，用于触发业务
      失败）；`if __name__ == "__main__"` 分支以 `mcp.run(transport="stdio")`
      启动，供 stdio 子进程测试直接执行；模块级导出 `mcp` 实例本身，供 HTTP
      测试在进程内以 `transport="streamable-http"` 启动
- [X] T003 [P] 创建空工具列表测试用 server
      tests/unit/tool/mcp_fixtures/empty_server.py：`FastMCP` 实例不注册
      任何工具，`if __name__ == "__main__"` 以 `mcp.run(transport="stdio")`
      启动（覆盖 spec Edge Cases 第 3 条"工具列表为空"场景）

**Checkpoint**: `python tests/unit/tool/mcp_fixtures/test_server.py` 与
`python tests/unit/tool/mcp_fixtures/empty_server.py` 均可作为 stdio 子进程
手动冒烟验证（Ctrl+C 退出），确认 R7 中列出的 SDK API 假设成立，如有出入
在此处修正后再继续

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构、异常层级、测试设施——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T004 实现配置与枚举 src/kernel/tool/mcp_models.py：frozen dataclass
      `McpServerConfig`（transport/command/url/headers/connect_timeout_seconds=10.0/
      discover_timeout_seconds=10.0/call_timeout_seconds=30.0，`__post_init__`
      校验 transport 与 command/url 匹配、超时字段均为正数，非法时抛
      `InvalidRequestError`，复用 001 异常）；`McpConnectionState` 枚举
      （NOT_CONNECTED/CONNECTED/CONNECT_FAILED/DISCONNECTED）；
      `DiscoveredMcpTool`（name/description/input_schema，data-model.md）
- [X] T005 [P] 实现异常层级 src/kernel/tool/mcp_errors.py：`McpError` 基类，
      `McpConnectionError`（detail）、`McpTimeoutError`（stage/timeout_seconds）、
      `McpDisconnectedError`（detail）、`McpToolExecutionError`（tool_name/detail）
      （research.md R4，data-model.md）
- [X] T006 [P] 扩展测试公共设施 tests/unit/tool/conftest.py：`mcp_stdio_command`
      fixture（拼接 `sys.executable` + `mcp_fixtures/test_server.py` 绝对路径）、
      `mcp_stdio_config`/`mcp_http_config` fixture（构造对应 `McpServerConfig`，
      测试用短超时加速失败场景）、空闲本地端口分配 helper（供 HTTP 测试启停
      后台 server 使用）
- [X] T007 [P] `McpServerConfig` 与异常层级单元测试
      tests/unit/tool/test_mcp_models.py：默认值正确；transport 与
      command/url 不匹配、任一超时字段 ≤0 时抛 `InvalidRequestError`；
      各异常类的诊断字段可正确构造与读取

**Checkpoint**: `pytest tests/unit/tool/test_mcp_models.py` 全绿

---

## Phase 3: User Story 1 - 接入本地 MCP server 并自动获得可用工具 (Priority: P1) 🎯 MVP

**Goal**: stdio 传输完成握手、`tools/list` 发现、适配为 `Tool` 并注册进
`ToolRegistry`、调用返回真实执行结果

**Independent Test**: 用 T002 的测试用 stdio server 驱动端到端流程——连接成功
→ 工具出现在注册表 → 调用 `echo` 工具返回预期结果，全程不依赖 US2/US3

- [X] T008 [US1] 实现连接编排 src/kernel/tool/mcp_client.py：`McpServerConnection`
      类——`__init__(config)`，`state` 属性（初始 `NOT_CONNECTED`）；`connect()`
      （stdio 分支：`mcp.client.stdio.stdio_client(...)` 建立读写流 +
      `ClientSession.initialize()`，用
      `asyncio.wait_for(timeout=connect_timeout_seconds)` 包裹，失败/超时
      分别抛 `McpConnectionError`/`McpTimeoutError(stage="connect")`，成功后
      `state` 置 `CONNECTED`，research.md R2/R3）；幂等性（data-model.md
      Edge Case 第 5 条）：`state == CONNECTED` 时重复调用直接返回（no-op，
      不重新握手）；`state` 为 `CONNECT_FAILED`/`DISCONNECTED` 时重复调用抛
      `McpConnectionError`（不支持原地重试）
- [X] T009 [US1] 在 src/kernel/tool/mcp_client.py 补全 `discover_tools()`：
      非 `CONNECTED` 状态（含从未连接的 `NOT_CONNECTED`）抛
      `McpDisconnectedError`；否则
      `asyncio.wait_for(session.list_tools(), timeout=
      discover_timeout_seconds)`，超时抛 `McpTimeoutError(stage="discover")`，
      成功后把每个工具转换为 `DiscoveredMcpTool` 列表返回
- [X] T010 [US1] 在 src/kernel/tool/mcp_client.py 补全 `call_tool(name,
      arguments)`：`asyncio.wait_for(session.call_tool(...), timeout=
      call_timeout_seconds)` 包裹；超时抛 `McpTimeoutError(stage="call")`；
      连接相关异常/非 `CONNECTED` 状态（含从未连接的 `NOT_CONNECTED`）抛
      `McpDisconnectedError`；返回结果标记 `isError` 时抛
      `McpToolExecutionError(tool_name, detail)`；否则把结果内容转换为
      字符串返回
- [X] T011 [US1] 在 src/kernel/tool/mcp_client.py 补全 `disconnect()`：关闭
      底层传输、`state` 置 `DISCONNECTED`，重复调用/对从未连接成功的实例
      调用均不抛异常（幂等，data-model.md）；span 埋点在 T026 补全
- [X] T012 [US1] 实现工具适配 src/kernel/tool/mcp_tool.py：`McpTool` 类，
      实现 001/002 冻结的 `Tool` Protocol，`invoke(arguments, tenant_id)`
      内部转调 `connection.call_tool(self.name, arguments)`（遥测在 Phase 6
      补全，此处先保证功能路径正确）
- [X] T013 [US1] 在 src/kernel/tool/mcp_tool.py 实现
      `register_mcp_tools(connection, registry)`：调用
      `connection.discover_tools()`，逐个构造 `McpTool` 并调用
      `registry.register(...)`；捕获重名导致的 `InvalidRequestError` 记入
      `RegisterMcpToolsResult.skipped`，不中断后续工具注册，返回
      `registered`/`skipped` 两个列表（research.md R5，FR-006/FR-009）
- [X] T014 [US1] 包级导出 src/kernel/tool/__init__.py 追加：按
      contracts/mcp-tool-adapter-api.md 导出 `McpServerConfig`、
      `McpConnectionState`、`DiscoveredMcpTool`、`McpServerConnection`、
      `McpTool`、`register_mcp_tools`、`RegisterMcpToolsResult`、
      `McpError` 及其四个子类（保留 005 已有导出不变）
- [X] T015 [P] [US1] stdio 握手与发现单元测试
      tests/unit/tool/test_mcp_connect_discover.py：`connect()` 对 T002 的
      测试用 server 握手成功、`state` 转为 `CONNECTED`（验收场景 US1-1）；
      `discover_tools()` 返回 3 个测试工具且名称/描述可读（验收场景 US1-2）；
      对 T003 的空工具列表测试用 server 连接成功、`discover_tools()` 返回
      空列表且不抛异常（spec Edge Cases 第 3 条，C3 修正项）；已 `CONNECTED`
      状态下重复调用 `connect()` 直接返回、不重新握手（spec Edge Cases 第
      5 条，C4 修正项）
- [X] T016 [P] [US1] 工具调用与 ReactEngine 兼容性单元测试
      tests/unit/tool/test_mcp_tool_invoke.py：`McpTool.invoke()` 调用
      `echo` 工具返回透传参数（验收场景 US1-3）；构造的 `McpTool` 可直接
      放入 002 `ReactEngine(tools=...)` 的字典参数而无需任何改动（对应
      contracts 行为契约 3）
- [X] T017 [P] [US1] 注册冲突单元测试
      tests/unit/tool/test_mcp_registry_conflict.py：`register_mcp_tools()`
      对一个已存在同名工具的 `ToolRegistry` 执行时，冲突工具被记入
      `skipped`、原工具不变，其余不冲突的工具正常进入 `registered`
      （FR-006，spec Edge Cases 第 1 条）

**Checkpoint**: US1 测试全绿——MVP 可演示（stdio 连接 → 发现 → 注册 → 调用的
完整闭环）

---

## Phase 4: User Story 2 - 接入远程 MCP server（HTTP 传输） (Priority: P2)

**Goal**: HTTP 传输下握手/发现/调用与 stdio 场景行为等价，调用方无感知差异

**Independent Test**: 用同一份 test_server.py 以 `streamable-http` 模式在测试
内启动，重复 US1 的连接/发现/调用验证，断言结果与 stdio 场景等价

- [ ] T018 [US2] 在 src/kernel/tool/mcp_client.py 的 `connect()` 补充 HTTP
      分支：`transport == "http"` 时使用
      `mcp.client.streamable_http.streamablehttp_client(url, headers=...)`
      建立读写流，之后复用与 stdio 分支相同的 `ClientSession.initialize()`
      与超时包裹逻辑（research.md R2）
- [ ] T019 [P] [US2] 扩展 tests/unit/tool/conftest.py：新增
      `mcp_http_server` fixture——在测试内以后台 `asyncio.Task` 启动
      T002 的 `mcp` 实例（`transport="streamable-http"`，绑定到已分配的
      空闲本地端口），yield 对应的 `McpServerConfig(transport="http",
      url=...)`，测试结束后取消后台任务
- [ ] T020 [P] [US2] HTTP 传输单元测试
      tests/unit/tool/test_mcp_http_transport.py：使用 `mcp_http_server`
      fixture 重复 US1 的握手/发现/`echo` 调用验证，断言行为与 stdio 场景
      完全等价（验收场景 US2-1/2）

**Checkpoint**: US1+US2 测试全绿——两种传输方式行为一致

---

## Phase 5: User Story 3 - 连接与调用失败时的可靠隔离 (Priority: P3)

**Goal**: 连接失败/超时/调用中途断连三类失败可区分，且单个连接的失败不影响
其他已注册工具

**Independent Test**: 分别用不可达命令/端口（连接失败）、`slow` 工具配合短
超时（调用超时）、`disconnect()` 后再调用（中途断连）驱动，同时验证同一
`ToolRegistry` 中另一个正常连接的工具不受影响

- [ ] T021 [US3] 在 src/kernel/tool/mcp_client.py 的 `connect()` 补全连接
      失败路径：stdio 目标命令不存在/无法启动、HTTP 地址不可达时统一抛
      `McpConnectionError(detail)`（区别于 T008 已实现的握手超时），
      `state` 置 `CONNECT_FAILED`（FR-008/FR-010，data-model.md 状态机）
- [ ] T022 [US3] 在 src/kernel/tool/mcp_client.py 的 `discover_tools()`/
      `call_tool()` 补全连接中途丢失的识别：已 `CONNECTED` 之后，若底层
      传输报告连接已关闭（如 stdio 子进程已退出、HTTP 连接被重置），统一
      抛 `McpDisconnectedError` 并将 `state` 转为 `DISCONNECTED`（FR-008，
      与 T010 已实现的 `isError` 业务失败路径互不覆盖）
- [ ] T023 [US3] 在 src/kernel/tool/mcp_tool.py 确认
      `register_mcp_tools()`/`McpTool.invoke()` 对单个连接失败的隔离性：
      一个 `McpServerConnection` 的失败（含 T021/T022 的各类异常）仅影响
      该连接产生的 `McpTool` 调用，不触碰 `ToolRegistry` 中其他条目
      （FR-009，若已由 T013/T012 的实现天然满足，此任务为补充针对性单测
      而非改动实现）
- [ ] T024 [P] [US3] 失败隔离单元测试
      tests/unit/tool/test_mcp_failure_isolation.py：连接一个不存在的
      stdio 命令 / 未监听的本地端口抛 `McpConnectionError`（验收场景
      US3-1）；对已连接的 server 调用配置了短 `call_timeout_seconds` 的
      `slow` 工具抛 `McpTimeoutError`（验收场景 US3-3）；`disconnect()`
      后再次调用其工具抛 `McpDisconnectedError`（验收场景 US3-2）；一个
      从未调用过 `connect()` 的全新 `McpServerConnection` 直接调用
      `discover_tools()`/`call_tool()` 同样抛 `McpDisconnectedError`（U1
      修正项）；与此同时，另一个独立、正常连接提供的工具（或 005
      `EchoTool`/`SandboxedTool`）在同一 `ToolRegistry` 中调用不受影响
      （FR-009）

**Checkpoint**: US1-US3 测试全绿——三类失败可分类识别且互不传染

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 遥测、演示脚本、文档收尾与最终验证

- [ ] T025 [P] 扩展遥测 src/kernel/tool/telemetry.py：新增
      `mcp_connection_span(tenant_id, transport)` 上下文管理器（span
      name 由调用方传入，供 `connect()` 传 `"mcp.connect"`、`disconnect()`
      传 `"mcp.disconnect"` 复用同一实现），复用 005 已建立的 tracer 与
      "遥测异常 try/except 不影响调用"约定（data-model.md span 契约）
- [ ] T026 集成遥测：在 src/kernel/tool/mcp_client.py 的 `connect()` 中
      用 `mcp_connection_span(..., span_name="mcp.connect")` 包裹并设置
      `result`（success/timeout/connection_error）；在 `disconnect()` 中
      用 `mcp_connection_span(..., span_name="mcp.disconnect")` 包裹（仅在
      本次调用实际执行了断开动作时才产生 span，`state` 已非 `CONNECTED`
      的 no-op 调用不重复产生，见 data-model.md `mcp.disconnect` span 契约）；在
      src/kernel/tool/mcp_tool.py 的 `McpTool.invoke()` 中复用 005 的
      `tool_invoke_span`（`tool.invoke` span），`result_type` 取值
      success/timeout/disconnected/tool_execution_failed（data-model.md）
- [ ] T027 [P] 遥测单元测试 tests/unit/tool/test_mcp_telemetry.py：
      `mcp.connect` span 含 `tenant_id`/`transport`/`result`；`disconnect()`
      产生一条 `mcp.disconnect` span 且重复调用 `disconnect()` 不重复产生
      （FR-010，C1 修正项）；`McpTool.invoke()` 产生的 `tool.invoke` span
      属性与 result_type 取值可区分；复用 005 的 `BrokenTracer` monkeypatch
      模式验证遥测失败不影响调用本身
- [ ] T028 [P] 创建演示脚本 examples/demo_mcp_client.py：按
      quickstart.md 第 2 节的预期输出，依次演示 stdio 连接发现调用、
      HTTP 连接发现调用（等价性）、调用超时、业务失败、主动断开后失败
      隔离，并打印每次连接/调用的 span
- [ ] T029 按 quickstart.md 全流程验证：`pytest tests/unit/tool -v -k mcp`
      全绿 → demo 脚本输出符合预期（SC-001/SC-003/SC-004）→ 计时确认
      15 分钟内完成，修复发现的问题；如 research.md R7 中的 SDK API 假设
      与实际不符，回写 research.md 记录差异（同 005 execvp bug 的处理方式）；
      SC-002（20 个工具数秒内完成发现）为参考性能预期，不设独立基准测试
      任务，同 001-005 对性能目标的既定处理方式（C2 修正项，仅需在此确认
      一致性，不要求新增测试）
- [ ] T030 更新 README.md roadmap：006 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：依赖 Phase 2 全部任务（配置/异常/测试设施），是后续两个故事的
  基础（`McpServerConnection`/`McpTool`/`register_mcp_tools` 均在 US1 建立）
- **US2**：依赖 US1 的 `McpServerConnection`/`connect()` 骨架，只新增 HTTP
  传输分支，不改动 stdio 路径
- **US3**：依赖 US1（连接/调用路径）与 US2（HTTP 场景下同样需要失败分类，
  但 T024 的核心断言可仅用 stdio 完成，US3 不阻塞于 US2 完成）
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 1 内：T002/T003 并行（互不依赖的独立测试用 server 脚本）
- Phase 2 内：T005/T006/T007 并行（T004 先行，因为 T007 依赖其定义的类型）
- US1 内：T008→T009→T010→T011 需按顺序在同一文件内演进；T012/T013 依赖
  T008-T011 完成；T015/T016/T017 三个测试文件可并行编写
- US2 内：T019/T020 可并行准备（T018 先行）
- US3 内：T021→T022 顺序演进（同文件）；T024 依赖 T021-T023
- Phase 6：T025/T027/T028 可并行，T026 依赖 T025，T029 依赖 T028，
  T027 依赖 T026

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T017）：stdio 传输下的连接、发现、适配、
注册、调用全链路可演示核心价值，且完全不需要 HTTP 传输或失败隔离验证通过。
随后 US2（HTTP 传输等价性）→ US3（失败分类与隔离）递增交付，最后 Polish
补齐遥测与演示脚本。每个 Checkpoint 处 `pytest` 必须全绿再前进。
