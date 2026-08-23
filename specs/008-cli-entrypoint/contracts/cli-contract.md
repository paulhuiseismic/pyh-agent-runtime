# Contract: CLI 命令行入口

## 命令形式

```text
pyh-agent <goal> [--session-id SESSION_ID] [--config CONFIG_PATH]
```

（`pyh-agent` 为 `pyproject.toml` `[project.scripts]` 声明的 console
script 名称；开发环境下等价于
`python -m platform_service.cli <goal> ...`，两者共用同一个
`cli.main()` 入口。）

- `goal`（位置参数，必需）：要提交给 agent 的目标/问题文本，不能为空
  字符串（空字符串视为参数校验失败，见下方退出码表）。
- `--session-id`（可选）：延续指定会话标识的历史上下文；省略则为全新
  会话。
- `--config`（可选）：平台配置文件路径；省略时读取
  `PLATFORM_SERVICE_CONFIG` 环境变量；两者都未提供视为配置缺失。

## 环境变量

| 变量名 | 必需性 | 说明 |
|--------|--------|------|
| `PLATFORM_SERVICE_API_KEY` | 必需 | 租户 API Key，用于 `resolve_tenant()`；未设置或为空视为"未提供 API Key" |
| `PLATFORM_SERVICE_CONFIG` | 必需（除非用 `--config` 显式提供） | 平台配置文件路径，结构同 007 `examples/platform_config.example.json` |

## 输出

- **成功**：最终结果文本写入 **stdout**（末尾追加换行），退出码 `0`；
  **stderr** 为空。
- **失败**：可读的失败原因描述写入 **stderr**（末尾追加换行），
  **stdout** 为空；退出码为下表对应值。

## 退出码

| 退出码 | 常量名 | 触发条件 | 是否触发过内核调用 |
|--------|--------|----------|-------------------|
| `0` | `EXIT_SUCCESS` | 成功完成一次调用 | 是 |
| `1` | `EXIT_MISSING_API_KEY` | 未设置 `PLATFORM_SERVICE_API_KEY` 环境变量 | 否 |
| `2` | `EXIT_AUTH_FAILED` | API Key 不匹配任何已配置租户 | 否 |
| `3` | `EXIT_CONFIG_INVALID` | 配置文件缺失/无法解析/字段非法（含模型未配置单价等 007 既有校验） | 否 |
| `4` | `EXIT_VALIDATION_FAILED` | `goal` 为空字符串 | 否 |
| `5` | `EXIT_TIMEOUT` | 处理耗时超过 `PlatformConfig.request_timeout_seconds` | 是（已发起，未完成） |
| `6` | `EXIT_KERNEL_ERROR` | `AgentService.handle()` 抛出未归类的内核异常 | 是 |
| `7` | `EXIT_QUOTA_EXCEEDED` | 租户当日累计成本达到 010 配置的 `daily_cost_quota_usd`（见 specs/010-multitenant-audit/contracts/audit-api.md） | 否 |

CLI 不复用 007 的 `ConcurrencyScheduler`，因此不存在
`EXIT_CONCURRENCY_EXCEEDED`——单进程单次调用没有真实的并发上限场景
需要保护（`/speckit-analyze` F1 修正项，research.md R3）。

上述退出码数值是本 feature 对外契约的一部分，一旦发布不得重新赋值
（新增失败类别时使用新的数值，不复用/不挪用已分配的数值）。

## 可观测性

一次成功或到达内核调用阶段的执行会产生与 007 REST 入口同名的
`platform.request` 根 span（`tenant_id`/`session_id`/`result` 属性），
其下嵌套 `AgentService.handle()` 触发的内核 span（`react.step`/
`chat {model}` 等），与 REST 入口的 span 层级完全一致（呼应
spec.md FR-007/SC-004）。`EXIT_MISSING_API_KEY`/`EXIT_AUTH_FAILED`/
`EXIT_CONFIG_INVALID`/`EXIT_VALIDATION_FAILED` 四类失败发生在
`platform.request` span 开始之前，不产生任何 span（与 007 未鉴权请求
的既有行为一致）。

## 与 007 REST 契约的对应关系

| CLI 退出码 | REST 对应响应（contracts/agent-run-api.md） |
|-----------|--------------------------------------------|
| `EXIT_MISSING_API_KEY` / `EXIT_AUTH_FAILED` | `401` |
| `EXIT_CONFIG_INVALID` | 启动期失败（REST 场景下体现为进程无法启动） |
| `EXIT_VALIDATION_FAILED` | `422`（请求体校验失败） |
| `EXIT_TIMEOUT` | `504` |
| `EXIT_KERNEL_ERROR` | `502` |

REST 入口的 `429`（并发上限超出）在 CLI 场景下没有对应退出码——CLI 不
复用 `ConcurrencyScheduler`（见上文）。
