# Research: MCP 客户端接入

## R1: 协议实现方式——官方 SDK vs 自研 JSON-RPC 客户端

**Decision**: 使用官方 Model Context Protocol Python SDK（PyPI 包名 `mcp`，MIT
license）完成 stdio/HTTP 传输、初始化握手、`tools/list`、`tools/call` 的协议层
实现；本 feature 只在其之上编写连接生命周期编排、超时包裹、错误分类、以及与
`Tool` Protocol / `ToolRegistry` 的适配层。

**Rationale**: 宪法原则 III 明确"能用成熟基础设施解决的问题 MUST NOT 自研"。
MCP 协议本身仍在演进（能力协商字段、分页等细节会随规范版本变化），自研客户端
意味着每次规范演进都要手动跟进；官方 SDK 由协议维护方本身维护，正确性与规范
兼容性有保证。此决策已在 `/speckit-plan` 前经用户显式确认（不同于历史 feature
自动复用既有依赖的情况，这是本 session 中第一次新增运行时依赖，遵循用户全局
规则"新增依赖前需先询问"）。

**Alternatives considered**:
- 手写 JSON-RPC 2.0 客户端（仅用现有 httpx + asyncio.subprocess）：不新增依赖，
  但需自行实现握手、能力协商、消息分帧，且未来协议演进需要手动跟进，违背
  原则 III；已在 spec 阶段前的 AskUserQuestion 中向用户提出并被否决。

## R2: stdio 与 HTTP 传输的上层接口统一

**Decision**: `McpServerConfig` 用一个 union 字段区分 stdio（`command: list[str]`）
与 HTTP（`url: str`, 可选 `headers: dict[str,str]`）两种传输目标；
`McpServerConnection.connect()` 内部根据配置类型选择官方 SDK 的
`mcp.client.stdio.stdio_client(...)`（stdio）或
`mcp.client.streamable_http.streamablehttp_client(...)`（HTTP）建立底层读写流，
再统一用 `mcp.ClientSession(read, write)` 完成握手；握手成功后，`discover_tools()`
/ `call_tool()` 对上层调用方而言与传输方式无关。

**Rationale**: spec US2 要求"调用方无法从工具的调用接口区分该工具来自 stdio
还是 HTTP 传输"；官方 SDK 的 `ClientSession` 本身就是传输无关的，两种
`*_client()` 只负责生成一对 anyio 读写流，天然适合在 `McpServerConnection`
内部做一次分支后复用同一套后续逻辑。

**Alternatives considered**:
- 为 stdio 和 HTTP 分别实现独立的 `Connection` 类：会导致 `McpTool`/
  `register_mcp_tools()` 要针对两种类型重复处理，违反原则 II（最简实现）。

## R3: 超时包裹策略

**Decision**: 握手（`connect()` 内的 `session.initialize()`）、工具发现
（`discover_tools()` 内的 `session.list_tools()`）、工具调用（`call_tool()`
内的 `session.call_tool()`）三处均用 `asyncio.wait_for(..., timeout=...)`
显式包裹，对应 `McpServerConfig` 上的三个独立超时字段（握手/发现/调用），
均有安全默认值、不允许配置为 0 或负数（复用 001/003/005 已建立的
"frozen dataclass + `__post_init__` 校验，非法值抛 `InvalidRequestError`"模式）。
超时触发时抛 `McpTimeoutError`，不依赖 SDK 自身是否内置超时（不同版本/传输
下 SDK 内置超时行为不一致，显式包裹是唯一能保证跨版本一致行为的方式）。

**Rationale**: 宪法原则 IV 要求所有外部调用禁止依赖库隐式默认值；005 已确立
"关键字段外部超时统一用 `asyncio.wait_for` 兜底"的先例（当时是因为
`httpx.MockTransport` 在测试中不遵守超时），这里延续同一模式。

**Alternatives considered**: 依赖 SDK 内部可能提供的超时参数——不采用，因为
其覆盖范围（是否包含握手阶段、是否包含底层传输层重试）未在 SDK 文档中显式
承诺为稳定契约，显式外层超时更可控、更符合"三个阶段独立可配置"的 spec 要求。

## R4: 错误分类映射

**Decision**: 定义 `McpError` 基类，四个具体类型：
- `McpConnectionError`：`connect()` 阶段任何失败（进程无法启动、HTTP 不可达、
  握手被拒绝）
- `McpTimeoutError`：握手/发现/调用任一阶段触发 R3 的超时
- `McpDisconnectedError`：已握手成功后，后续调用中发现连接已不可用（读写流
  关闭、SDK 抛出连接相关异常）
- `McpToolExecutionError`：`call_tool()` 成功往返但 MCP server 在
  `CallToolResult.isError` 中标记该次调用为业务失败（与 005
  `SandboxToolExecutionError` 同级语义——协议往返成功，业务结果是失败）

**Rationale**: 对应 spec FR-008 要求区分四类失败；复用 001（`ProviderError`
子类划分）、005（`SandboxError`/`SandboxToolExecutionError` 划分）已确立的
"基础设施失败 vs 业务失败"分层，调用方（`ReactEngine`）可以按已有习惯统一
`except` 处理，不需要为 MCP 工具引入新的异常处理路径。

**Alternatives considered**: 复用 005 的 `SandboxError` 层级本身——不采用，
因为 MCP 连接的失败模式（进程/网络连接持续存在、可能中途断开）与沙箱工具
"单次调用即结束的子进程"模型不同，中途断连（`McpDisconnectedError`）在
沙箱模型中不存在，需要独立的异常层级表达。

## R5: 已发现工具与 ToolRegistry 的重名处理

**Decision**: 不在 MCP 层做任何重名检测或覆盖逻辑；`register_mcp_tools()`
辅助函数逐个把适配好的 `McpTool` 传给调用方已持有的 `ToolRegistry.register()`，
重名冲突时沿用 005 已实现的行为（抛 `InvalidRequestError`，不覆盖已注册工具），
`register_mcp_tools()` 对外返回"成功注册的工具列表"与"因重名被跳过的工具列表"，
不让单个工具的注册失败中断其余工具的注册流程。

**Rationale**: spec FR-006 要求复用已有的重名拒绝行为；005 的 `ToolRegistry`
契约已经冻结（"重复注册同名工具被拒绝"是 005 的验收标准之一），不应该为 MCP
场景引入不同语义（如"后注册覆盖先注册"），避免同一个注册表在不同工具来源下
出现不一致的重名策略。

**Alternatives considered**: 在适配层做去重预检查后静默跳过——不采用，因为
"报告冲突"是 FR-006 的显式要求，调用方需要知道哪些工具因为重名没有被注册。

## R6: 测试用 MCP server 的构造方式

**Decision**: 使用官方 SDK 提供的 `mcp.server.fastmcp.FastMCP` 快速构造测试用
server（`tests/unit/tool/mcp_fixtures/stdio_server.py`），暴露 3 个测试工具
（`echo`：原样返回入参；`slow`：sleep 一段可配置时长，用于触发调用超时；
`fail`：显式返回 `isError=True`，用于触发 `McpToolExecutionError`）。stdio
传输场景下作为真实子进程启动（`sys.executable stdio_server.py`）；HTTP 传输
场景下同一份 server 逻辑以 `transport="streamable-http"` 模式在测试内以后台
`asyncio.Task` 启动、测试结束后关闭，不依赖对外网络暴露。连接失败场景用
"不存在的可执行文件路径"（stdio）与"未监听的本地端口"（HTTP）模拟；连接中途
断开场景通过在测试中主动终止 stdio 子进程 / 关闭 HTTP 后台任务模拟。

**Rationale**: 复用 005 已确立的"用最小可控的测试用脚本代替真实第三方系统"
思路（005 用 `sleep_forever.py`/`exit_nonzero.py` 等 fixture 脚本模拟沙箱场景）；
`FastMCP` 是官方 SDK 内置的测试/开发用便利 API，用它编写测试 server 本身也是
"组装优先于自研"的体现，不需要手写符合协议的 server 端逻辑。

**Alternatives considered**: 只做协议层 mock（不启动真实 server 进程/任务）——
不采用，因为 spec 的验收标准明确要求"端到端验证连接成功→发现→调用"，纯 mock
无法验证与真实 SDK 传输层的集成正确性，也无法复现 005 曾经踩过的"看似正确但
在真实进程/平台差异下出错"的问题类型（如 005 的 Windows execvp bug）。

## R7: 实现阶段验证事项（Setup checkpoint 已用真实 SDK 验证，替换此前的预期）

Setup checkpoint 实际安装的是 `mcp` 2.0.0（PyPI 最新主版本，非本文档撰写时
参考的旧版 API 形状），用 stdio 与 streamable-http 两种传输各跑通一次真实
握手 + 发现 + 调用的 smoke test 后，确认以下与撰写时预期不同的实际 API 形状
（同 005 execvp bug 的处理方式，实现阶段发现真实差异后回写本文档）：

- **高层 server 类不叫 `FastMCP`**：本版本中位于
  `mcp.server.mcpserver.MCPServer`（`from mcp.server.mcpserver import
  MCPServer`），构造与 `tool()` 装饰器用法与预期的 `FastMCP` 一致，仅类名与
  导入路径不同；测试用 server（`tests/unit/tool/mcp_fixtures/test_server.py`/
  `empty_server.py`）已改用此导入
- **HTTP 传输的运行方式**：不存在 `mcp.settings.host/port` 可写属性；启动
  HTTP 模式须显式调用 `await server.run_streamable_http_async(host=...,
  port=...)`（`run(transport="streamable-http", **kwargs)` 内部就是转发到
  这个方法），`conftest.py` 的 `mcp_http_server` fixture 按此调用
- **HTTP 传输客户端函数名**：是 `mcp.client.streamable_http.
  streamable_http_client`（下划线分隔），不是预期的 `streamablehttp_client`
- **`ClientSession` 返回对象字段均为 snake_case**（pydantic 模型属性），
  非驼峰：`InitializeResult.server_info`（非 `serverInfo`）、
  `Tool.input_schema`（非 `inputSchema`）、`CallToolResult.is_error`
  （非 `isError`）
- **stdio 与 streamable-http 两种 `*_client()` 返回值形状一致**：均为
  async context manager，yield 一个可解包为 `(read_stream, write_stream)`
  的二元结构（`len(streams) == 2`），验证了 research.md R2 的"传输无关"设计
  假设成立，`McpServerConnection.connect()` 可用同一段"解包 (read, write) +
  构造 ClientSession"逻辑处理两种传输
- **连接失败的异常形状因传输而异**：stdio 目标命令不存在时，
  `stdio_client()` 直接抛出标准库 `FileNotFoundError`；HTTP 地址不可达时，
  `streamable_http_client()` 抛出 anyio `ExceptionGroup`（包裹底层
  `httpx2` 连接异常）。两者类型不同，`McpServerConnection.connect()` 的
  连接失败处理 MUST 用 `except Exception`（而非某个具体异常类型）统一捕获
  并转换为 `McpConnectionError(detail=str(e))`，不依赖判断具体异常类型
- **业务失败时的 `content`**：`call_tool()` 对抛异常的工具函数自动返回
  `is_error=True`，`content` 中包含形如 `Error executing tool {name}:
  {原始异常信息}` 的 `TextContent`，`McpToolExecutionError` 的 `detail`
  取该文本内容即可，无需额外包装
- **工具返回值序列化**：工具函数返回 `dict` 时，SDK 自动将其序列化为
  JSON 文本包装进 `TextContent`（`text` 字段为 JSON 字符串），
  `McpServerConnection.call_tool()` 的成功路径直接取 `content[0].text`
  作为返回字符串即可，无需自行 `json.dumps`

## R8: 实现阶段发现的真实 bug——跨 Task 的 anyio 取消作用域冲突

**问题**：US3 阶段编写"HTTP 地址不可达"的失败隔离测试时，`connect()`
稳定复现 `RuntimeError: Attempted to exit cancel scope in a different task
than it was entered in`，而不是预期的 `McpConnectionError`。

**根因**：最初实现用 `asyncio.wait_for(_do_connect(), timeout=...)` 包裹整个
"建立传输 + 建 `ClientSession` + 握手"过程，其中 `_do_connect()` 内部通过
`AsyncExitStack.enter_async_context(...)` 逐个进入 `stdio_client`/
`streamable_http_client`/`ClientSession` 这些基于 anyio 的上下文管理器。
`asyncio.wait_for` 会把被等待的协程包装为一个独立的 `asyncio.Task` 来运行——
于是 `enter_async_context` 的调用实际发生在这个"临时任务"里，而失败时的
`stack.aclose()` 却是从 `connect()` 自身所在的（调用方）任务里发起的。
anyio 的取消作用域（cancel scope）与其创建时所在的 Task 绑定，跨 Task 调用
`__aexit__` 必然报错——这与 005 的 Windows execvp 退出码丢失 bug同属"标准库/
第三方库对 Task 边界隐含假设，在特定调用模式下才会暴露"的问题类型。

**修复**：`connect()` 改为不再用 `wait_for` 包裹整个建连过程，而是在
`connect()` 自身所在的 Task 内直接 `await stack.enter_async_context(...)`
（不经过任何任务包装）；只对其中真正的"纯协程调用"（`session.initialize()`，
不涉及任何上下文管理器的进入/退出）单独用 `asyncio.wait_for` 包裹超时。这样
`AsyncExitStack` 的进入与（无论成功后 `disconnect()` 还是失败时的
`stack.aclose()`）退出，全程都发生在同一个 Task 里。

**附带发现**：修复上述问题后，"HTTP 地址不可达"场景在 `streamable_http_client`
内部仍会在其自身的 anyio 任务组清理阶段抛出同类 `RuntimeError`——这是该 SDK
版本（`mcp` 2.0.0）自身在"连接在其内部任务组产出 (yield) 之前就失败"这一
路径下的实现问题，不是我们代码可以从外部规避的。**最终方案**：在进入
`streamable_http_client` 之前，先用一次独立的 `asyncio.open_connection(host,
port)`（不涉及任何 anyio 任务组）做 TCP 可达性探测，探测失败直接抛
`McpConnectionError`，探测成功才进入 `streamable_http_client`——把"连接被拒绝"
这类失败挡在触发该 SDK 内部 bug 之前。此发现与规避方案已在
`src/kernel/tool/mcp_client.py` 的 `_preflight_tcp_check()` 中以注释形式记录。

## R9: 实现阶段发现的真实约束——同一 Task 内多个连接必须按 LIFO 顺序 disconnect()

**问题**：编写 `examples/demo_mcp_client.py`（同一个 `main()` 协程内先后
建立一个 stdio 连接和一个 HTTP 连接，用于演示"断开一个连接不影响另一个"）时，
先 `disconnect()` **先建立**的那个连接（stdio），复现
`RuntimeError: Attempted to exit a cancel scope that isn't the current
tasks's current cancel scope`。用最小复现脚本进一步验证：两个
`McpServerConnection`（哪怕都是同一种 stdio 传输）在同一个 asyncio Task 内
建立后，若按**非**"后建立先断开"的顺序调用 `disconnect()`，稳定复现同一个
`RuntimeError`；按 LIFO 顺序（后连接的先断开）则完全正常。

**根因**：`stdio_client`/`streamable_http_client`/`ClientSession` 内部各自
用 `anyio.create_task_group()` 开辟一个取消作用域（cancel scope）。同一个
asyncio Task 上的取消作用域按**严格栈序（LIFO）**组织——若同一任务内先后
`enter_async_context` 了连接 A 的作用域、再进入连接 B 的作用域，则必须先
退出 B、再退出 A；若先退出 A（此时 B 的作用域仍"晚于" A 存在于该任务的
作用域栈中），anyio 会检测到栈序被打破并报错。这不是我们代码的 bug，而是
anyio 取消作用域模型的固有约束——只是在"同一任务内维护多个长生命周期的
MCP 连接"这一使用模式下才会暴露（与 R8 同属实现阶段才发现的真实约束）。

**应对**：不在 `McpServerConnection`/`register_mcp_tools` 层面强制单例或
排队限制（那会过度限制上层灵活性，也不是 spec 要求的行为），而是把这一约束
显式记录为使用须知：**在同一个 asyncio Task 内维护多个 `McpServerConnection`
时，调用方 MUST 按与 `connect()` 相反的顺序（后连接的先断开）调用
`disconnect()`**；`examples/demo_mcp_client.py` 已按此顺序实现并在代码注释
中说明。spec FR-009（"单个连接失败不影响其他工具"）本身不受此约束影响——
该约束只出现在显式 `disconnect()` 的收尾阶段，不出现在连接失败、调用失败、
或调用中途断连的路径中（这些路径均已被 US3 的测试覆盖且不涉及跨连接的
LIFO 冲突）。若未来的平台层（007+）需要在同一任务内管理多个 MCP 连接的
生命周期，MUST 遵循此约束，或改为每个连接使用独立的 asyncio Task
（不同 Task 各自维护独立的取消作用域栈，天然不受此限制）。
