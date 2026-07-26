# Implementation Plan: 长期记忆

**Branch**: `004-long-term-memory` | **Date**: 2026-07-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-long-term-memory/spec.md`

## Summary

在 `src/kernel/memory/` 内新增独立子模块 `long_term.py`/`extraction.py`，实现
`LongTermMemory`：`extract()`（显式触发，接收会话历史，经一次 provider LLM
调用提炼出带类别标注的记忆条目并 upsert 写入）与 `query()`（按 tenant_id +
数量上限、按写入时间倒序返回）。持久化复用 003 的 SQLite（WAL）方案，
新增独立表 `memory_entries`，通过 `UNIQUE(tenant_id, category)` +
SQLite 对 NULL 的"总是不同"语义，天然实现"同类别覆盖、无法判定类别独立新增"
（FR-008），不写任何应用层分支逻辑。与 003 的会话消息表/压缩逻辑完全不共享
代码路径。

## Technical Context

**Language/Version**: Python 3.12（延续 001/002/003）

**Primary Dependencies**: 无新增——复用 003 已引入的 `aiosqlite`、
001 的 `kernel.provider`（提炼时发起 LLM 调用）、`opentelemetry-api`/`-sdk`

**Storage**: SQLite（WAL 模式，与 003 会话消息表共享数据库文件但为独立新表
`memory_entries`）；测试用真实临时文件（延续 003 R8 的测试策略）

**Testing**: pytest + pytest-asyncio；provider 用 001/002/003 已验证的
`httpx.MockTransport` stub（脚本化返回结构化 JSON 提炼结果）

**Target Platform**: 同 001/002/003

**Project Type**: library（内核 memory 子模块的独立扩展）

**Performance Goals**: 单次 extract/query 的存储层开销 <20ms（参考值，不作为
验收标准、不设基准测试任务，同 001/002/003 的处理方式）

**Constraints**: 不与 003 的会话消息存储、自动压缩逻辑耦合（FR-012）；
查询接口设计不假设排序方式，为未来语义检索留出替换空间（FR-007）；
提炼不自动触发，必须显式调用（FR-003，区别于 003 的自动压缩）

**Scale/Scope**: 约 4-5 个源文件 + 单元测试；不涉及平台层、不涉及向量检索

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | long_term 子模块仅依赖 kernel.provider（内核内部依赖，延续 002/003 模式），不 import 平台层 | ✅ 通过 |
| II. 最简实现 | 冲突处理借助 SQLite `UNIQUE` 约束 + NULL 语义原生实现，不写应用层分支/实体消解逻辑 | ✅ 通过 |
| III. 组装优先 | 零新增第三方依赖（复用 003 的 aiosqlite） | ✅ 通过 |
| IV. 超时与成本上限 | 提炼的 LLM 调用经 provider 发起，自动继承其超时/token/成本上限 | ✅ 通过 |
| V. OTel GenAI 可观测 | extract/query 各发一个 span 含 tenant_id + 操作类型；提炼内部的 provider 调用 span 为其子 span（FR-011） | ✅ 通过 |
| VI. 测试与安全边界 | 数量上限必须为正整数（FR-006）；模块全场景单测（FR-009） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入新依赖或新抽象，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/004-long-term-memory/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   └── long-term-memory-api.md  # LongTermMemory 对上层暴露的接口契约
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/kernel/memory/
├── ...（001/003 已交付的 provider 无关部分不变）
├── long_term_models.py    # MemoryEntry / ExtractionResult（frozen dataclass）
├── extraction.py          # 提炼提示构造与结构化输出解析（同 002 prompting 模式）
├── long_term_storage.py   # LongTermStore：memory_entries 表的 upsert/查询
├── long_term.py           # LongTermMemory：编排 extraction + storage + 遥测
└── telemetry.py           # 复用/扩展：long_term_memory.{operation} span

tests/unit/memory/
├── test_long_term_models.py     # 数据结构校验
├── test_extraction.py           # 提炼提示构造与结构化输出解析
├── test_long_term_extract.py    # US1：提炼写入、空结果不写入、provider 失败不写脏数据
├── test_long_term_query.py      # US2：数量上限排序、空库返回空、跨租户隔离
├── test_long_term_conflict.py   # US3：同类别覆盖、不同类别独立、反复提炼不无限增长
└── test_long_term_telemetry.py  # 遥测：tenant_id/操作类型、父子 span
```

**Structure Decision**: 延续 001/002/003 的单包 library 布局；长期记忆作为
`kernel.memory` 包内的独立文件集合（不建子包，因文件数量少，避免过度目录化，
呼应最简原则），与 003 的会话记忆文件（`storage.py`/`compaction.py` 等）
并列存在但零交叉 import。
