# Research: 平台服务层 + web service（REST API）

## R1: Web 框架选型——FastAPI + uvicorn

**Decision**: 使用 FastAPI（MIT license）作为 REST 框架，uvicorn（MIT，已因
006 安装 `mcp` SDK 而存在于依赖树中）作为 ASGI 服务器。

**Rationale**: 宪法原则 III 要求成熟基础设施优先于自研；FastAPI 原生 async、
与内核已有的 asyncio 设计天然契合，且基于 pydantic 自动完成请求体校验，
直接满足 FR-007"请求参数校验失败"这一独立可区分的失败类别，无需手写校验
逻辑。此决策已在 `/speckit-plan` 前经用户显式确认（与 006 引入 MCP SDK
同样的"新增依赖需先询问"流程）。

**Alternatives considered**:
- Starlette（FastAPI 底层的 ASGI 工具包）：更轻量，但不自带请求校验，
  需要手写 FR-007 要求的校验失败判断逻辑，增加实现量且价值有限；已在
  AskUserQuestion 中向用户提出并被否决。
- Python 标准库 `http.server`/`wsgiref`：不新增依赖，但需要自行实现路由、
  JSON 解析、异步事件循环整合——等同于自研一个迷你 Web 框架，直接违反
  原则 II/III。

## R2: 并发调度器实现方式——进程内计数器，非 asyncio.Semaphore

**Decision**: `ConcurrencyScheduler` 用两个纯 Python 计数器实现——一个
`dict[tenant_id, int]`（每租户当前处理中的请求数）与一个全局 `int`，
配合一个 `asyncio.Lock` 保护"检查上限 + 计数 +1"这一步的原子性；
`try_acquire(tenant_id)` 在超限时直接抛 `ConcurrencyLimitExceededError`
（FR-012 已确认的"立即拒绝"），不阻塞等待；`release(tenant_id)` 在请求
处理结束（无论成功/失败）时于 `finally` 块调用，保证计数器不泄漏。

**Rationale**: `asyncio.Semaphore` 的 `acquire()` 在无可用许可时会挂起
等待，不符合 FR-012"立即拒绝而非排队"的要求；虽然 `Semaphore` 提供
`locked()` 属性可用于非阻塞检查，但"检查 `locked()` 后再 `acquire()`"
存在竞态窗口（两次调用之间可能被其他协程抢先），在高并发场景下会导致
超过配置上限。手写的"锁保护的检查+自增"是最简单且能保证原子性的方式，
不引入额外的第三方限流库（呼应原则 II/III）。

**Alternatives considered**:
- `asyncio.Semaphore` + `locked()` 检查：存在上述竞态问题，废弃。
- 引入第三方限流库（如 `aiolimiter`）：本 feature 的限流语义足够简单
  （固定上限、立即拒绝、无令牌桶/滑动窗口等复杂策略），自行实现的计数器
  已经是最简方案，不需要新增依赖。

## R3: 会话记忆（003）/长期记忆（004）与 ReactEngine（002）的整合方式

**Decision**: 002 冻结的 `ReactEngine.run(goal, *, tenant_id, max_steps)`
只接受单个字符串 `goal`，不接受外部消息列表或系统提示——这是已冻结接口，
本 feature MUST NOT 修改。因此 `AgentService.handle()` 在调用
`ReactEngine.run()` 之前，把「已查询到的长期记忆事实（如有）+ 会话历史
（如提供了 session_id）+ 本次用户问题」拼接为一个纯文本 `goal` 字符串
传入；调用成功后，把「本次用户问题」与「最终答案」各自作为一条消息
`append()` 进 003 的会话记忆（如提供了 session_id）。长期记忆的写入
（事实提炼）复用 004 `LongTermMemory.extract()`，在本次调用的历史消息
基础上异步提炼，提炼失败不影响本次请求已经产生的结果（best-effort，
与遥测失败隔离同样的"失败不传染"原则）。

**Rationale**: 复用 examples/demo_cross_conversation_memory.py 已验证的
"先查长期记忆注入上下文、后写会话历史"模式，不需要为 ReactEngine 新增
接受消息列表的重载（那将改变 002 已冻结的契约，违反宪法原则关于接口
兼容性的隐含要求）。把整合逻辑放在平台层的 `AgentService` 而不是内核，
正是宪法原则 I"内核不感知平台"的体现——内核不需要知道"多轮会话"这个
平台层概念。

**Alternatives considered**:
- 修改 `ReactEngine.run()` 签名以直接接受历史消息列表：被拒绝，因为
  002 的接口已在此前 feature 冻结，修改会波及所有已依赖它的调用方
  （005/006 的测试与 demo），不符合"只做兼容式扩展"的既定原则。
- 长期记忆提炼同步阻塞在请求返回之前完成：会增加请求整体耗时且违背
  "提炼失败不应影响本次请求结果"的隔离要求，故改为 best-effort。

## R4: ToolRegistry 与 MCP 连接的生命周期——应用启动时构建一次，全请求共享

**Decision**: `ToolRegistry`（含本地工具、005 沙箱工具、006 MCP 工具）
在 FastAPI 应用启动时（ASGI lifespan）构建一次，作为长生命周期对象被
所有请求共享；MCP server 连接同样在启动时建立一次，不随每次请求重新
连接/断开。

**Rationale**: 006 的 `McpServerConnection` 设计本身就是"建立一次、
长期复用、支持多次 `call_tool()`"的模型，重新连接的开销（进程启动/
HTTP 握手）不应该摊到每次用户请求上；`ToolRegistry` 本身也是无状态的
只读查找结构（`get`/`as_dict`），天然适合被多个并发请求共享，不需要
每请求重建。

**Alternatives considered**:
- 每请求构建新的 `ToolRegistry`/MCP 连接：显著增加每次请求的延迟，
  且与 006 已验证的"MCP 连接是长生命周期资源"设计相悖。

## R5: 请求整体超时的实现方式——asyncio.wait_for 包裹 AgentService.handle()

**Decision**: `app.py` 用 `asyncio.wait_for(agent_service.handle(request,
tenant_id=tenant_id), timeout=platform_config.request_timeout_seconds)`
包裹对 `AgentService` 的调用；超时抛出的 `asyncio.TimeoutError` 被
捕获并转换为平台层的 `RequestTimeoutError`，映射为对应的 HTTP 状态码
（FR-009）。这是"纯协程调用"的等待，不涉及 006 research.md R8 中发现
的"跨 Task 的 AsyncExitStack 进入/退出"问题（`AgentService.handle()`
内部不持有跨请求存活的上下文管理器，`ToolRegistry`/MCP 连接由 R4
决定在应用启动时的另一个生命周期管理，不在每次请求的 `wait_for` 范围内）。

**Rationale**: 与 006 已确立的"外层超时统一用 `asyncio.wait_for` 兜底"
模式一致；由于 R4 已经把长生命周期资源（MCP 连接、ToolRegistry）的
建立/销毁移出单次请求的处理路径，这里不会重蹈 006 R8 的问题。

## R6: 测试策略——FastAPI 应用的端到端测试不监听真实端口

**Decision**: `test_app.py` 使用 `httpx.AsyncClient(transport=
httpx.ASGITransport(app=app))` 直接在内存中调用 ASGI 应用，不启动真实
TCP 监听；内核调用（LLM）继续复用 001 已确立的 `httpx.MockTransport`
stub 模式，工具调用复用 005 的示例脚本 fixture 与 006 的测试用 MCP
server fixture。全程无网络依赖、无真实模型密钥。

**Rationale**: 延续 001-006"stub 化、零外部依赖"的测试哲学；
`httpx.ASGITransport` 是 FastAPI/Starlette 官方推荐的测试方式，不需要
额外的测试专用依赖（`fastapi.testclient.TestClient` 底层也是基于同样
的机制，两者等价，这里直接用 httpx 版本以复用项目已有的 httpx 依赖）。
