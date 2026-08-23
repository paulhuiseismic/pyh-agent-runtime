# Implementation Plan: 多租户强化与审计

**Branch**: `010-multitenant-audit` | **Date**: 2026-08-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-multitenant-audit/spec.md`

## Summary

在既有 `src/platform_service/` 包内新增一个独立模块 `audit.py`
（`AuditStore`，aiosqlite 持久化，与 003 `SqliteMemory` 同风格），并把
"记录一次请求的用量/成本"与"配额检查"这两个新能力**集中放入
`AgentService.handle()` 内部**（而不是在 REST/CLI/消息网关三个入口
各自实现一遍）——这是唯一能同时满足 spec.md FR-003（复用同一处理
路径）与 FR-008（不引入第二套用量统计口径）的位置，因为 `AgentService`
是三个入口唯一共同复用的处理路径。三个入口各自只需新增一个
`except QuotaExceededError` 分支把这个新异常映射为各自形式的"配额
超限"响应，与它们已有的"映射内核异常为对应失败响应"的既有模式完全
一致，不引入新的架构层次。

关键技术难题——`ReactEngine.run()`（002，已冻结）只返回最终答案
文本，不返回本次调用的 token 用量/成本——通过一个**不改动任何冻结
内核接口**的方案解决：`AgentService._handle_locked()` 为每次调用构造
一个轻量的委托包装器 `_UsageTrackingProvider`（只在 `handle()` 内部
临时存在，作用域仅限单次调用，无跨请求状态污染风险），把它（而不是
共享的 `self._provider`）传给本次调用新建的 `ReactEngine`；包装器
转发全部 `complete()` 调用到真实 provider，同时把每次响应的
`usage`/`cost_usd` 累加起来，`engine.run()` 返回后即可读取本次调用的
总用量/成本用于写入审计记录。见 research.md R1。

## Technical Context

**Language/Version**: Python 3.12（延续 001-009）

**Primary Dependencies**: 无新增第三方依赖——复用已有的 `aiosqlite`
（`AuditStore` 与 003 `SqliteMemory`/004 `LongTermMemory` 同类实现
风格）、`fastapi`（新增查询端点）

**Storage**: 新增 `platform_audit.db`（SQLite，`aiosqlite` 异步驱动，
延续 003/004 的技术选型与默认 db 路径命名风格）；不复用/不修改
`session_memory_db_path`/`long_term_memory_db_path` 指向的既有表

**Testing**: pytest + pytest-asyncio；`AuditStore` 用真实临时 SQLite
文件驱动（同 003/004 既有测试风格，验证持久化跨连接可查询，SC-003）；
用量累加包装器与配额检查用 stub provider（复用 001
`httpx.MockTransport` 模式）驱动 `AgentService.handle()` 端到端验证；
REST 查询端点用 `httpx.ASGITransport`

**Target Platform**: 同 001-009（Linux server 生产 / Windows 本地开发）

**Project Type**: web service 扩展（在既有 `platform_service` 平台层
包内新增一个独立模块 + 对三个既有入口的兼容式扩展，不新建独立顶层包）

**Performance Goals**: 不设精确基准，同 007-009；查询端点是一次本地
SQLite 聚合查询，不涉及网络调用或内核调用，不需要 `ConcurrencyScheduler`/
`asyncio.wait_for` 包裹（研究阶段判定其耗时特征与 LLM 调用完全不同，
research.md R3）

**Constraints**: MUST NOT 修改 001（`LLMProvider`）/002（`ReactEngine`）
已冻结的内核公共接口；对 `AgentService.__init__`/`handle()` 的扩展
MUST 是向后兼容的（新增可选参数，默认值保证 007-009 已有调用方/测试
零改动即可继续通过）；配额检查所用的累计成本 MUST 直接来自
`AuditStore` 已持久化的记录，MUST NOT 引入第二套统计口径（FR-008）；
审计写入失败 MUST NOT 影响原始请求结果（FR-003）

**Scale/Scope**: 1 个新源文件（`platform_service/audit.py`）+ 扩展
`agent_service.py`/`config.py`/`errors.py`/`app.py`/`cli.py`/
`message_gateway.py`/`__init__.py` + 单元测试 + 一个演示脚本；不涉及
运行时动态租户管理 API、不涉及跨租户查询、不涉及非按天的配额窗口

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | `audit.py` 只依赖标准库/`aiosqlite`，不依赖内核；`agent_service.py` 的扩展仍只单向 import `kernel.*`；内核（001/002）代码零改动 | ✅ 通过 |
| II. 最简实现 | 用量累加通过一个几十行的委托包装器实现，不引入 OTel SpanProcessor 式的全局状态方案（research.md R1 已排除，理由：跨测试/跨进程的处理器生命周期管理会引入不必要的复杂度与脆弱性）；配额窗口固定按天，不做可配置窗口长度；查询端点默认仅返回调用方自身租户数据，不新增权限体系（均为按需最简选择） | ✅ 通过 |
| III. 组装优先 | 复用已有 `aiosqlite` 依赖，无新增第三方组件，无需更新 THIRD_PARTY.md | ✅ 通过 |
| IV. 超时与成本上限 | 新增的"按天累计成本配额"是在 001 已有"单次调用成本上限"之上的第二层保护（两者并存，互不替代，spec.md Assumptions）；`AuditStore` 的 SQLite 本地文件 I/O 不涉及网络调用，不适用"外部调用超时"要求（与 003/004 既有 `SqliteMemory`/`LongTermMemory` 的既有处理方式一致） | ✅ 通过 |
| V. OTel GenAI 可观测 | 配额超限（`QuotaExceededError`）在三个入口各自已有的 span 包裹范围内传播，各入口新增一个 `span.set_result("quota_exceeded")` 分支，与已有的 `concurrency_exceeded`/`kernel_error`/`timeout` 等分支风格一致；审计记录本身不替代 OTel span，是面向"无需部署 Langfuse 即可回答基本用量问题"的补充能力（spec.md Assumptions） | ✅ 通过 |
| VI. 测试与安全边界 | `audit.py` 与对既有模块的扩展均按宪法附加约束补充单元测试；查询端点只允许调用方查询自身租户数据（FR-005），不引入跨租户数据泄露风险；配置了配额的租户，其配额检查通过 `QuotaLockRegistry` 串行化，消除并发场景下的超额放行竞态（`/speckit-analyze` F1 修正，research.md R6） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物对 `AgentService.__init__`/`handle()`
的扩展均为新增可选参数（默认值保证现有调用方为向后兼容行为），
`TenantConfig`/`PlatformConfig` 新增字段均可选且有安全默认值，
007-009 已有测试与生产配置文件无需任何改动即可继续通过，六项门禁
维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/010-multitenant-audit/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── audit-api.md      # 查询端点契约 + AgentService 扩展契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/platform_service/
├── audit.py（新增）         # `AuditEntry`（dataclass：tenant_id/source/
│                           # timestamp/input_tokens/output_tokens/
│                           # cost_usd/status）、`UsageSummary`
│                           # （dataclass：tenant_id/start/end/
│                           # request_count/total_input_tokens/
│                           # total_output_tokens/total_cost_usd）；
│                           # `AuditStore`（aiosqlite，同 SqliteMemory
│                           # 风格）——`record(entry)`（简单
│                           # INSERT，异常正常抛出，由调用方决定是否
│                           # best-effort 吞掉，FR-003）、
│                           # `query_usage(tenant_id, start, end) ->
│                           # UsageSummary`（聚合 SUM/COUNT）、
│                           # `sum_cost_since(tenant_id, since) ->
│                           # float`（配额检查用）、`aclose()`
├── config.py（扩展）        # `TenantConfig` 新增可选字段
│                           # `daily_cost_quota_usd: float | None =
│                           # None`（校验 > 0 若提供）；`PlatformConfig`
│                           # 新增 `audit_db_path: str =
│                           # "platform_audit.db"`；
│                           # `load_config_from_file` 相应解析
├── errors.py（扩展）        # 新增 `QuotaExceededError(tenant_id,
│                           # quota_usd)`（独立于内核异常层级，同
│                           # `ConcurrencyLimitExceededError` 风格）
├── agent_service.py（扩展） # `build_agent_service()` 额外构造
│                           # `AuditStore(config.audit_db_path)` 并
│                           # 注入；`AgentService.__init__` 新增可选
│                           # 关键字参数 `audit_store:
│                           # AuditStore | None = None`（向后兼容——
│                           # 007-009 现有直接构造 `AgentService(...)`
│                           # 的测试/demo 零改动继续通过，此时审计/
│                           # 配额均静默跳过）；`handle()` 新增可选
│                           # 关键字参数 `source: str = "unknown"`
│                           # （FR-001 的来源入口字段，向后兼容）；
│                           # 新增 `QuotaLockRegistry`（内部，同
│                           # `SessionLockRegistry` 写法，按
│                           # `tenant_id` 惰性创建/复用
│                           # `asyncio.Lock`）；`handle()` 在配置了
│                           # `daily_cost_quota_usd` 的租户上，用该
│                           # 锁把"配额检查 → 内核调用 → 审计记录
│                           # 写入"整段临界区串行化（`/speckit-analyze`
│                           # F1 修正，research.md R6；未配置配额的
│                           # 租户不经过此锁，零开销）；加锁顺序固定
│                           # 为"先配额锁（如适用），再会话锁（如
│                           # 适用）"，避免与既有 `SessionLockRegistry`
│                           # 产生锁顺序反转；`_handle_locked()`
│                           # 内部：1) 若 `audit_store` 与租户
│                           # `daily_cost_quota_usd` 均已配置，
│                           # `await audit_store.sum_cost_since(tenant_id,
│                           # 今日 UTC 零点)`，达到或超过配额时抛
│                           # `QuotaExceededError`（FR-007，先于任何
│                           # `ReactEngine`/`LLMProvider` 调用；此时
│                           # 已持有配额锁，读到的是最新数据）；
│                           # 2)（原有流程不变）；3) 用内部类
│                           # `_UsageTrackingProvider`（委托包装
│                           # `self._provider`，累加每次
│                           # `complete()` 响应的 usage/cost_usd）
│                           # 构造本次调用专用的 `ReactEngine`；4)
│                           # 成功后（若 `audit_store` 非空）
│                           # `await audit_store.record(...)`
│                           # status="success"，包在 try/except 内，
│                           # 失败仅 `logger.warning`（FR-003）；5)
│                           # 内核异常时同样（best-effort）记录
│                           # status="failure"（用量记录累加器此刻
│                           # 已捕获到失败前发生的部分调用用量）后
│                           # 重新抛出原异常（外部可见行为不变，
│                           # 只新增了旁路的审计写入副作用）
├── app.py（扩展）           # lifespan 中 `agent_service`/`build_agent_service`
│                           # 已内含 `audit_store` 构造（`agent_service.py`
│                           # 变更即生效，`app.py` 本身只需新增两处）：
│                           # 1) `/v1/agent/run` 端点调用 `handle()`
│                           # 时补充 `source="rest"`，并在既有异常
│                           # 处理链路中新增
│                           # `except QuotaExceededError` 分支——
│                           # `span.set_result("quota_exceeded")`，
│                           # 映射 HTTP 402（区别于并发超限的 429）；
│                           # 2) 新增 `GET /v1/audit/usage` 端点——
│                           # 读取 `X-API-Key` 解析出 tenant_id（复用
│                           # `resolve_tenant`，鉴权失败沿用 401）、
│                           # 可选 query 参数 `start`/`end`
│                           # （ISO8601，缺省分别为当日 UTC 零点/当前
│                           # 时间）→ `await
│                           # app.state.agent_service._audit_store
│                           # .query_usage(tenant_id, start, end)`
│                           # → 返回 `UsageSummary`；只查询调用方
│                           # 自身租户，不接受外部传入的 tenant_id
│                           # 参数（FR-005，从设计上排除越权可能）
├── cli.py（扩展）           # `run()` 调用 `service.handle(...)` 时
│                           # 补充 `source="cli"`；新增退出码常量
│                           # `EXIT_QUOTA_EXCEEDED=7`（追加而非重排，
│                           # 遵守 008 contracts/cli-contract.md
│                           # "新增失败类别使用新数值"的既有约定）；
│                           # 新增 `except QuotaExceededError` 分支
├── message_gateway.py（扩展） # `_process_and_callback()` 调用
│                           # `handle()` 时补充
│                           # `source="message_gateway"`；新增
│                           # `except QuotaExceededError` 分支——
│                           # 出站回调 payload `status="quota_exceeded"`
│                           # （复用既有的 status/error 字段结构，
│                           # 不新增字段）
└── __init__.py（扩展）      # 追加导出 `AuditStore`、`AuditEntry`、
                            # `UsageSummary`、`QuotaExceededError`

tests/unit/platform_service/
├── conftest.py（扩展）      # 新增：临时 SQLite 路径下的 `AuditStore`
│                           # fixture；一个已配置
│                           # `daily_cost_quota_usd` 的 `TenantConfig`
│                           # 变体
├── test_audit.py（新增）    # `AuditStore` 单元测试：`record`+
│                           # `query_usage` 汇总正确、`sum_cost_since`
│                           # 只计入窗口内记录、进程重启（新连接指向
│                           # 同一文件）后仍可查询（SC-003）、无记录
│                           # 时间范围返回全零汇总
├── test_agent_service.py（扩展） # 新增：`handle()` 成功时写入
│                           # 一条 status="success" 审计记录（用量/
│                           # 成本与 stub provider 响应一致）；内核
│                           # 失败时写入 status="failure" 记录并仍
│                           # 正常向上抛出原异常；`audit_store=None`
│                           # 时（既有 007-009 测试的默认构造方式）
│                           # 行为不受影响；累计成本达到
│                           # `daily_cost_quota_usd` 后抛
│                           # `QuotaExceededError`，且未触发
│                           # `ReactEngine`/`provider`（用会在被调用
│                           # 时断言失败的哨兵 provider 验证）
├── test_app_audit.py（新增） # `GET /v1/audit/usage` 端到端：合法
│                           # 查询返回正确汇总、无记录时间范围返回
│                           # 全零、鉴权失败 401、`/v1/agent/run`
│                           # 配额超限返回 402
├── test_cli.py（扩展）      # `EXIT_QUOTA_EXCEEDED` 场景
└── test_message_gateway.py（扩展） # `status="quota_exceeded"`
                            # 场景

examples/demo_audit.py（新增） # 演示：正常调用产生审计记录 → 查询
                              # 汇总 → 配额耗尽后新请求被拒绝
examples/platform_config.example.json（扩展） # 新增
                                             # `daily_cost_quota_usd`/
                                             # `audit_db_path` 字段示例
```

**Structure Decision**: 不新建独立顶层包——`audit.py` 加入既有
`platform_service` 包；用量记录与配额检查的核心逻辑集中在
`agent_service.py` 内部（唯一被三个入口共同复用之处），三个入口
（`app.py`/`cli.py`/`message_gateway.py`）各自只做"新增一个来源标识
参数 + 新增一个异常分支"这种最小化、模式一致的适配，不新增任何跨
入口共享之外的抽象层，完全符合 spec.md FR-003/FR-008 的复用约束。
