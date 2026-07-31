# Contract: MCP 客户端与 Tool/ToolRegistry 适配公共接口

**Consumer**: 平台层调度器（未来 feature 007，负责按租户配置需要连接的 MCP
server）、react 模块（002 `ReactEngine` 已冻结的 `tools: dict[str, Tool]`
构造参数，可用 005 `ToolRegistry.as_dict()` 产出）
**Provider**: `kernel.tool`（在 005 已交付内容之上扩展）

数据结构见 [data-model.md](../data-model.md)。

## 公共导出（`kernel.tool` 包级，新增部分）

```python
from kernel.tool import (
    # 005 已冻结导出（不变）：
    Tool, EchoTool, ToolRegistry,
    SandboxedTool, SandboxLimits, SandboxError, ...,

    # 006 新增：
    McpServerConfig,
    McpConnectionState,
    DiscoveredMcpTool,
    McpServerConnection,
    McpTool,
    register_mcp_tools,
    RegisterMcpToolsResult,
    McpError,
    McpConnectionError,
    McpTimeoutError,
    McpDisconnectedError,
    McpToolExecutionError,
)
```

## 行为契约

1. `McpServerConnection.connect()` MUST 在握手完成（协议初始化成功）之后
   才将 `state` 置为 `CONNECTED`；握手失败或超时 MUST 抛
   `McpConnectionError` / `McpTimeoutError`，MUST NOT 静默返回。
2. `McpServerConnection.discover_tools()` MUST 仅在 `state == CONNECTED`
   时可成功执行；非 `CONNECTED` 状态下调用 MUST 抛 `McpDisconnectedError`。
3. `McpTool` MUST 满足 001/002 冻结的 `Tool` Protocol，MUST 可直接用于
   构造 002 `ReactEngine(tools=...)` 的工具集合，与 005 `SandboxedTool`
   混用时 ReactEngine 侧无需任何改动或分支判断。
4. `register_mcp_tools()` 对发现的每个工具逐个调用
   `ToolRegistry.register()`；单个工具因与已注册工具重名而被拒绝时，
   MUST 记入返回结果的 `skipped` 列表并继续处理其余工具，MUST NOT 中断
   整体注册流程，MUST NOT 覆盖已存在的同名工具。
5. `McpTool.invoke()` 的全部失败路径（连接失败/超时/连接中断/业务失败）
   MUST 通过抛出 `McpError` 子类反馈，MUST NOT 返回 `None` 或静默失败。
6. 每次 `McpServerConnection.connect()`（含失败）MUST 产生一条 `mcp.connect`
   span，携带 `tenant_id`/`transport`/`result`；每次 `McpTool.invoke()`
   （含全部失败路径）MUST 产生一条 `tool.invoke` span，携带
   `tenant_id`/`tool_name`/`result_type`/`duration_seconds`；遥测失败
   MUST NOT 影响调用本身的执行与结果。
7. 单个 `McpServerConnection` 的连接失败、超时或断开 MUST NOT 影响同一
   `ToolRegistry` 中其他工具（本地工具、005 沙箱工具、其他 MCP 连接提供的
   工具）的正常调用。
8. `McpServerConnection.disconnect()` MUST 幂等（对已断开或从未连接成功的
   实例重复调用不抛异常）；断开后该连接产生的所有 `McpTool` 实例的
   `invoke()` MUST 抛 `McpDisconnectedError`。

## 兼容性承诺

- 不修改 001/002 已冻结的 `Tool` Protocol 与 `ReactEngine` 契约。
- 不修改 005 已冻结的 `ToolRegistry`/`SandboxedTool` 公共方法签名与行为。
- `McpServerConfig` 字段只增不删，新增字段须有安全默认值。
- `McpServerConnection`/`McpTool` 的公共方法签名冻结后只做兼容式扩展。
