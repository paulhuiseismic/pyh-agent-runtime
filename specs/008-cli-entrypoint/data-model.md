# Data Model: CLI 入口（复用平台服务层）

本 feature 不引入任何新的持久化实体或数据库表——数据模型层面只是对
既有 007 实体（`PlatformConfig`/`TenantConfig`/`AgentRunRequest`/
`AgentRunResult`）的复用，以及新增的进程级（非持久化）CLI 调用参数/
结果结构。

## 复用的既有实体（零改动）

- **`PlatformConfig`** / **`TenantConfig`**（`platform_service/config.py`）：
  CLI 与 REST 读取同一结构的配置文件（`load_config_from_file`），CLI
  场景下不需要其中任何"仅服务于网络监听"的字段（本身也没有这类字段——
  007 的 `PlatformConfig` 已是纯粹的"平台行为配置"，不含端口/host 等
  REST 专属项，天然可被 CLI 直接复用）。
- **`AgentRunRequest`** / **`AgentRunResult`**（`platform_service/models.py`）：
  CLI 把命令行参数适配为 `AgentRunRequest(goal=..., session_id=...)`
  传给 `AgentService.handle()`，其返回的 `AgentRunResult` 直接用于
  拼装终端输出文本（`result.answer`）。
- **`AgentService`**（含内部 `SessionLockRegistry`）：行为零改动，CLI
  只是新增一个调用方。CLI 不复用 007 的 `ConcurrencyScheduler`——单进程
  单次调用没有真实存在的并发上限场景需要保护，引入它只会产生一个无法
  被真实触发的检查路径（`/speckit-analyze` F1 修正项，research.md R3）。

## 新增的进程级结构（不持久化）

### CLI 调用参数（对应 spec.md「CLI 调用参数」实体）

| 字段 | 来源 | 必需性 | 说明 |
|------|------|--------|------|
| `goal` | 命令行位置参数 | 必需，非空字符串 | 对应 `AgentRunRequest.goal` |
| `session_id` | `--session-id` 命令行参数 | 可选 | 对应 `AgentRunRequest.session_id`；省略时为 `None`（全新会话） |
| `config_path` | `--config` 参数，缺省读 `PLATFORM_SERVICE_CONFIG` 环境变量 | 必需（两者之一必须提供） | 传给 `load_config_from_file()` |
| `api_key` | `PLATFORM_SERVICE_API_KEY` 环境变量 | 必需 | 传给 `resolve_tenant()`；不通过命令行参数传入（FR-002） |

### CLI 调用结果（对应 spec.md「CLI 调用结果」实体）

一次 `cli.run()` 调用的返回值为 `tuple[int, str, str]`
（退出码、stdout 文本、stderr 文本），三者互斥使用：

- 成功：退出码 `EXIT_SUCCESS`（0），stdout 为 `AgentRunResult.answer`
  文本（末尾换行），stderr 为空。
- 失败：退出码为对应失败类别常量（见 contracts/cli-contract.md），
  stdout 为空，stderr 为可读的失败原因描述。

`main()` 是 `run()` 的薄包装：读取 `sys.argv`/`os.environ`，把
`run()` 返回的 stdout/stderr 文本分别写入 `sys.stdout`/`sys.stderr`，
并以返回的退出码调用 `sys.exit()`。

## 状态转换

CLI 单次调用不涉及跨调用的状态机——每次 `run()` 调用都是从"读取参数"
到"输出结果并返回退出码"的一次性线性流程，唯一跨调用的状态是通过
`session_id` 显式关联的会话历史（存储在 `SqliteMemory`，行为完全由
007 已有实现决定，CLI 不新增任何状态管理）。
