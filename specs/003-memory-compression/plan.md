# Implementation Plan: memory 压缩与上下文管理

**Branch**: `003-memory-compression` | **Date**: 2026-07-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-memory-compression/spec.md`

## Summary

在 `src/kernel/memory/` 中实现 `SqliteMemory`，替换 001 的 `NoopMemory` 占位实现，
`Memory` Protocol 签名不变。消息按 `(tenant_id, session_id)` 持久化到 SQLite
（WAL 模式，`aiosqlite` 异步驱动）；`append`/`load` 在检测到累计 token 超预算时
自动触发压缩——将超出"最近保留窗口"的较早消息通过一次 `LLMProvider.complete()`
调用生成摘要并替换；压缩失败时 provider 异常原样上抛、原始数据不受影响。
每次操作发出携带 `session_id`/`tenant_id`/是否压缩的 span。测试用真实临时
SQLite 文件 + stub provider，零平台层依赖。

## Technical Context

**Language/Version**: Python 3.12（延续 001/002）

**Primary Dependencies**: `aiosqlite`（新增，异步 SQLite 驱动，MIT license，
需登记 THIRD_PARTY.md）；`kernel.provider`（压缩时发起 LLM 调用，内核内部依赖，
延续 002 与 provider 的依赖模式）；`opentelemetry-api`/`opentelemetry-sdk`
（已是既有依赖，无新增）

**Storage**: SQLite（WAL 模式），单表 `messages`（见 data-model.md），
默认文件路径可配置，测试用 `tempfile` 临时文件（真实文件系统，非 mock）

**Testing**: pytest + pytest-asyncio；SQLite 用真实临时文件（验证真实持久化，
不 mock 存储层）；provider 用 001/002 已验证的 `httpx.MockTransport` stub

**Target Platform**: 同 001/002

**Project Type**: library（内核子模块）

**Performance Goals**: 单次 append/load 的存储层开销 <20ms（参考值，不作为
验收标准、不设基准测试任务——WAL 模式下 SQLite 单机读写延迟通常远低于此，
同 001/002 的处理方式）

**Constraints**: 不改变 001 冻结的 `Memory` Protocol 签名；压缩不可逆
（Assumptions）；不支持会话删除/导出导入（Assumptions）；不引入分布式锁
组件，并发保护借助 SQLite 自身机制（Assumptions）

**Scale/Scope**: 约 5-6 个源文件 + 单元测试；不涉及平台层、不涉及多实例
部署下的存储扩展（README 已记录：出现真实多实例需求时再迁 PostgreSQL）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | memory 仅依赖 kernel.provider（内核内部依赖，延续 002 模式），不 import 平台层 | ✅ 通过 |
| II. 最简实现 | 单表 SQLite、无 ORM；并发保护用 SQLite 自身串行化，不引入分布式锁（Assumptions） | ✅ 通过 |
| III. 组装优先 | SQLite 是标准库能力的异步封装（aiosqlite），非自研存储引擎；新增依赖登记 THIRD_PARTY.md | ✅ 通过 |
| IV. 超时与成本上限 | 压缩的 LLM 调用经 provider 发起，自动继承其超时/token/成本上限（FR-006） | ✅ 通过 |
| V. OTel GenAI 可观测 | 每次 load/append 发 span 含 session_id/tenant_id/压缩标注（FR-008）；压缩内部 LLM 调用继承 provider 的 tenant_id span | ✅ 通过 |
| VI. 测试与安全边界 | memory 模块单元测试覆盖全部场景（FR-010）；预算/保留窗口有安全默认值，不允许"不压缩"（Assumptions） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入新抽象或新依赖之外的组件，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/003-memory-compression/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── memory-api.md     # Memory 对上层暴露的接口契约（复用 001 签名）
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/kernel/memory/
├── __init__.py           # 导出 Memory Protocol、SqliteMemory（替换 NoopMemory）、配置类型
├── models.py              # ContextBudget（预算/保留窗口配置，安全默认值）
├── storage.py             # SqliteStore：底层表结构、增删查（不含压缩逻辑）
├── compaction.py          # 压缩判定与执行：估算 token、决定压缩范围、调 provider 生成摘要
└── telemetry.py           # memory 操作 span：session_id/tenant_id/是否压缩

tests/unit/memory/
├── conftest.py            # 临时 SQLite 文件 fixture、stub provider 工厂（复用 001/002 模式）
├── test_storage.py             # US1：持久化读写、跨租户隔离、空会话、重启后可读
├── test_compaction.py          # US2：超预算自动压缩、保留窗口、未超预算不压缩、压缩失败不丢数据
└── test_memory_telemetry.py    # US3：操作 span、压缩标注、遥测容错
```

**Structure Decision**: 延续 001/002 的单包 library 布局，`memory` 子包内部按
职责拆分（存储层与压缩逻辑分离，压缩逻辑单独可测试而不必每次触发真实存储 IO）。
