# Data Model: MCP 客户端接入

**Date**: 2026-07-31 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

## McpServerConfig（配置，frozen dataclass，见 `mcp_models.py`）

| 字段 | 类型 | 默认值 | 约束 |
|------|------|--------|------|
| transport | `Literal["stdio", "http"]` | 无（必填） | 决定使用 `command` 还是 `url` 分支 |
| command | `list[str] \| None` | `None` | `transport == "stdio"` 时必填且非空 |
| url | `str \| None` | `None` | `transport == "http"` 时必填 |
| headers | `dict[str, str] \| None` | `None` | 仅 HTTP 传输可选使用（如鉴权 token） |
| connect_timeout_seconds | float | 10.0 | > 0（握手阶段超时，research.md R3） |
| discover_timeout_seconds | float | 10.0 | > 0（`tools/list` 阶段超时） |
| call_timeout_seconds | float | 30.0 | > 0（`tools/call` 阶段超时） |

构造时校验（`__post_init__`）：`transport` 与 `command`/`url` 不匹配、任一超时
字段 ≤ 0 → `InvalidRequestError`（复用 001 异常，与 003/004/005 的校验风格一致）。

## 异常层级（`mcp_errors.py`，见 research.md R4）

```text
McpError(Exception)
├── McpConnectionError       # connect() 阶段失败：detail: str
├── McpTimeoutError          # stage: "connect"|"discover"|"call", timeout_seconds: float
├── McpDisconnectedError     # 已握手成功后，后续操作发现连接不可用：detail: str
└── McpToolExecutionError    # 协议往返成功但业务失败：tool_name: str, detail: str
```

四类异常均携带足够诊断信息，供调用方（或 002 `ReactEngine` 转化出的
`Observation.content`）展示失败原因；不新增聚合父类区分"基础设施失败"与
"业务失败"，因为调用方（`ReactEngine._invoke_tool`）已对任意异常统一捕获转为
观察结果，不依赖细分的公共父类分支。

## McpConnectionState（枚举，`mcp_models.py`）

```text
NOT_CONNECTED → CONNECTED → DISCONNECTED
              ↘ CONNECT_FAILED
```

- `NOT_CONNECTED`：初始状态，尚未调用 `connect()`
- `CONNECTED`：握手成功，可以 `discover_tools()`/`call_tool()`
- `CONNECT_FAILED`：`connect()` 失败（终态，需要新建连接实例重试，不支持原地重连）
- `DISCONNECTED`：`disconnect()` 主动断开，或 `call_tool()` 发现连接已丢失后
  自动转入此状态（终态）

`DISCONNECTED`/`CONNECT_FAILED` 状态下调用 `discover_tools()`/`call_tool()`
MUST 直接抛 `McpDisconnectedError`，不重新尝试连接（呼应 spec Assumptions：
v1 不做自动重连）。`NOT_CONNECTED` 状态下（从未调用过 `connect()`）调用
`discover_tools()`/`call_tool()` 同样 MUST 直接抛 `McpDisconnectedError`
（不区分"从未连接"与"已断开"两种未就绪状态的错误类型，调用方只需处理一种
异常）。

`connect()` 的幂等性（spec Edge Cases 第 5 条）：`state == CONNECTED` 时
重复调用 `connect()` MUST 直接返回（no-op），MUST NOT 重新握手、MUST NOT
产生新的 `mcp.connect` span；`state` 为 `CONNECT_FAILED`/`DISCONNECTED` 时
重复调用 `connect()` MUST 抛 `McpConnectionError`（沿用"需新建连接实例重试，
不支持原地重连"的既有约定，不静默重试）。

## DiscoveredMcpTool（`mcp_models.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | MCP server 声明的工具名 |
| description | str | MCP server 声明的工具描述 |
| input_schema | dict | MCP server 声明的输入参数 JSON Schema（原样保留，不做语义校验，research.md R7） |

## McpServerConnection（`mcp_client.py`）

```python
class McpServerConnection:
    def __init__(self, config: McpServerConfig) -> None: ...

    @property
    def state(self) -> McpConnectionState: ...

    async def connect(self) -> None: ...
        # 建立底层传输（stdio_client / streamablehttp_client） + ClientSession.initialize()
        # 失败 → McpConnectionError；超时 → McpTimeoutError(stage="connect")

    async def discover_tools(self) -> list[DiscoveredMcpTool]: ...
        # 失败/未连接 → McpDisconnectedError；超时 → McpTimeoutError(stage="discover")

    async def call_tool(self, name: str, arguments: dict) -> str: ...
        # 协议往返失败/连接丢失 → McpDisconnectedError
        # 超时 → McpTimeoutError(stage="call")
        # 返回内容标记 isError → McpToolExecutionError(tool_name, detail)
        # 成功 → 返回结果内容转换后的字符串

    async def disconnect(self) -> None: ...
        # 主动关闭底层传输，状态转 DISCONNECTED，幂等（重复调用不报错，
        # 且不重复产生 mcp.disconnect span）；产生一条 mcp.disconnect span
        # （见"遥测 span 契约"一节，对应 FR-010 的"断开"生命周期事件）
```

## McpTool（`mcp_tool.py`，实现 001 冻结的 `Tool` Protocol）

```python
class McpTool:
    name: str
    description: str

    def __init__(
        self, *, name: str, description: str,
        connection: McpServerConnection,
    ) -> None: ...

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str: ...
        # 包一层 tool.invoke span（复用 005 telemetry.py），内部转调
        # connection.call_tool(self.name, arguments)
```

## register_mcp_tools（`mcp_tool.py`，编排函数）

```python
async def register_mcp_tools(
    connection: McpServerConnection, registry: ToolRegistry,
) -> RegisterMcpToolsResult: ...
```

```text
RegisterMcpToolsResult:
  registered: list[str]   # 成功注册的工具名
  skipped: list[tuple[str, str]]  # (工具名, 冲突原因) —— 重名时来自
                                  # ToolRegistry.register() 抛出的 InvalidRequestError
```

行为（对应 research.md R5、spec FR-006/FR-009）：对 `discover_tools()` 返回的
每个工具逐个构造 `McpTool` 并调用 `registry.register(...)`；捕获重名导致的
`InvalidRequestError` 记入 `skipped`，不中断后续工具的注册；一个工具注册失败
不影响同一批次其他工具、也不影响该 registry 中此前已注册的任何工具。

## 状态流转（一次典型使用序列）

```text
connection = McpServerConnection(config)
  → await connection.connect()
      ├─ 失败/超时 → McpConnectionError / McpTimeoutError(stage="connect")
      │   （状态转 CONNECT_FAILED，需新建实例重试，不支持原地重连）
      └─ 成功 → 状态转 CONNECTED
  → result = await register_mcp_tools(connection, registry)
      内部: await connection.discover_tools()
              ├─ 超时 → McpTimeoutError(stage="discover")
              └─ 成功 → 逐个 registry.register(McpTool(...))
                          ├─ 重名 → 记入 result.skipped，继续下一个
                          └─ 成功 → 记入 result.registered
  → （后续，ReactEngine 通过 registry.as_dict() 拿到 Tool 后）
    await tool.invoke(arguments, tenant_id=...)
      内部: await connection.call_tool(name, arguments)
              ├─ 超时 → McpTimeoutError(stage="call")
              ├─ 连接已断开 → McpDisconnectedError
              ├─ isError 标记 → McpToolExecutionError(tool_name, detail)
              └─ 成功 → 字符串结果
  → await connection.disconnect()  # 主动断开，产生 mcp.disconnect span，
                                    # 之后调用一律 McpDisconnectedError
```

## 遥测 span 契约

### `mcp.connect`（新增，见 research.md R3）

| 属性 | 值 |
|------|-----|
| span name | `mcp.connect` |
| `tenant_id` | 发起连接的调用方传入 |
| `transport` | `"stdio"` / `"http"` |
| `result` | `success` / `timeout` / `connection_error` |
| span status | 成功 OK；失败 ERROR + 异常类名 |

### `mcp.disconnect`（新增，对应 FR-010"断开"生命周期事件）

| 属性 | 值 |
|------|-----|
| span name | `mcp.disconnect` |
| `tenant_id` | 发起断开的调用方传入 |
| `transport` | `"stdio"` / `"http"` |
| span status | 恒为 OK（`disconnect()` 幂等且不抛异常，无失败态需要区分） |

`state != CONNECTED` 时重复调用 `disconnect()`（no-op）MUST NOT 重复产生此
span，避免同一次断开动作在遥测中出现多条重复记录。

### `tool.invoke`（复用 005 已有 span，见 005 `data-model.md`）

`McpTool.invoke()` 复用与 `SandboxedTool.invoke()` 完全相同的 `tool.invoke`
span 命名与属性集合（`tenant_id`/`tool_name`/`result_type`/`duration_seconds`），
`result_type` 在 MCP 场景下取值为 `success` / `timeout` / `disconnected` /
`tool_execution_failed`，与 005 的取值集合并列但互不冲突（调用方按
`Tool.invoke()` 统一接口消费，不感知底层是沙箱还是 MCP）。
