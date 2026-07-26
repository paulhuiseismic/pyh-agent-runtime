# Contract: tool 注册中心与沙箱执行公共接口

**Consumer**: 平台层调度器（未来 feature 007）、react 模块（002 ReactEngine 已冻结的
`tools: dict[str, Tool]` 构造参数，可用 `ToolRegistry.as_dict()` 产出）
**Provider**: `kernel.tool`

数据结构见 [data-model.md](../data-model.md)。

## 公共导出（`kernel.tool` 包级）

```python
from kernel.tool import (
    Tool,                          # Protocol（001 已冻结，签名不变）
    EchoTool,                      # 001 交付的占位实现，保留
    ToolRegistry,
    SandboxedTool,
    SandboxLimits,
    SandboxError,
    SandboxInfraError,
    SandboxTimeoutError,
    SandboxResourceExceededError,
    SandboxStartupError,
    SandboxToolExecutionError,
)
```

## 行为契约

1. `ToolRegistry.register()` 对重名工具 MUST 抛 `InvalidRequestError`
   （复用 001 异常），原有工具 MUST 保持不变。
2. `ToolRegistry.get()` 对未注册的名称 MUST 返回 `None`，MUST NOT 抛异常。
3. `SandboxedTool` 满足 001/002 冻结的 `Tool` Protocol，MUST 可直接用于
   构造 002 `ReactEngine(tools=...)` 的工具集合，无需 ReactEngine 侧
   任何改动。
4. `SandboxedTool.invoke()` 的全部失败路径（超时/资源超限/启动失败/
   非零退出码）MUST 通过抛出 `SandboxError` 子类反馈，MUST NOT 返回
   `None` 或静默失败。
5. 每次 `invoke()`（含全部失败路径）MUST 产生一条 `tool.invoke` span，
   携带 `tenant_id`/`tool_name`/`result_type`/`duration_seconds`；
   遥测失败 MUST NOT 影响调用本身的执行与结果。
6. CPU/内存资源限制 MAY 因运行平台不同而实际约束力不同（仅 POSIX 硬性
   生效）；超时限制 MUST 在所有平台强制生效。
7. 本 feature MUST NOT 声称提供网络隔离；调用方 MUST NOT 依赖
   `SandboxedTool` 阻止目标命令发起网络请求。

## 兼容性承诺

- `ToolRegistry`/`SandboxedTool` 的公共方法签名冻结后只做兼容式扩展。
- `SandboxLimits` 字段只增不删，新增字段须有安全默认值。
- 不修改 001/002 已冻结的 `Tool` Protocol 与 `ReactEngine` 契约。
