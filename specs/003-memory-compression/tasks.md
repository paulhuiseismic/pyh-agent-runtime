---

description: "Task list for memory 压缩与上下文管理"
---

# Tasks: memory 压缩与上下文管理

**Input**: Design documents from `/specs/003-memory-compression/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`kernel.provider`、`Memory` Protocol 已交付）

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试（FR-010），
不适用模板的"测试可选"约定。

**Organization**: 按用户故事分组；US1（存储层）是 US2（压缩）与 US3（遥测）的
共同基础，US2/US3 均在 `compaction.py` 上演进。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

延续 001/002 的单包 library 布局：`src/kernel/memory/`、`tests/unit/memory/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 依赖声明与目录骨架，全部后续任务的前提

- [ ] T001 在 pyproject.toml 中新增依赖 `aiosqlite`（异步 SQLite 驱动）
- [ ] T002 创建目录骨架：tests/unit/memory/ 目录、tests/unit/memory/__init__.py
- [ ] T003 [P] 在 THIRD_PARTY.md 中登记 aiosqlite（MIT license）

**Checkpoint**: `pip install -e ".[dev]"` 成功安装 aiosqlite，`pytest tests/unit/memory` 可运行（0 tests）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构与测试设施——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [ ] T004 实现配置结构 src/kernel/memory/models.py：frozen dataclass ContextBudget
      （max_context_tokens 默认 4000、keep_recent_messages 默认 6，均校验为正整数）（data-model.md，research.md R4）
- [ ] T005 [P] 创建测试公共设施 tests/unit/memory/conftest.py：临时 SQLite 文件路径 fixture
      （tempfile.TemporaryDirectory，真实文件而非 :memory:，research.md R8）、复用 001/002 的
      scripted stub provider 工厂（httpx.MockTransport，按调用顺序返回预设摘要文本）、price_table fixture
- [ ] T006 [P] ContextBudget 校验单元测试 tests/unit/memory/test_models.py：默认值正确、
      非正数字段被拒绝

**Checkpoint**: `pytest tests/unit/memory/test_models.py` 全绿

---

## Phase 3: User Story 1 - 会话消息的持久化读写 (Priority: P1) 🎯 MVP

**Goal**: 按 (tenant_id, session_id) 持久化读写消息，跨租户隔离，重启后可读

**Independent Test**: 用真实临时 SQLite 文件追加/读取消息，验证顺序完整、
跨租户隔离、空会话返回空列表、重新打开连接后数据仍在

- [ ] T007 [US1] 实现存储层 src/kernel/memory/storage.py：SqliteStore 类——
      建表（PRAGMA journal_mode=WAL）、append_row（事务内 SELECT MAX(seq)+1 后 INSERT，
      research.md R3 并发保护）、load_rows（按 tenant_id+session_id 查询，按 seq 排序）、
      replace_rows（删除指定 seq 集合 + 插入新行，同一事务，供 T013 压缩复用）（data-model.md 表结构）
- [ ] T008 [US1] 实现 SqliteMemory 骨架 src/kernel/memory/__init__.py 或临时占位：
      __init__(db_path, provider, model, budget)、load()/append() 先调用 storage 层完成
      基础读写（暂不含压缩逻辑，压缩逻辑在 US2 补全）、aclose()（contracts/memory-api.md）
- [ ] T009 [P] [US1] 持久化读写单元测试 tests/unit/memory/test_storage.py：
      依次追加 3 条消息后读取顺序一致（验收场景 US1-1）；重新创建 SqliteMemory 实例指向
      同一 db_path 验证数据仍在（验收场景 US1-2，SC-005）；不存在的 session_id 返回空列表
      不报错（验收场景 US1-4，FR-003）
- [ ] T010 [P] [US1] 跨租户隔离单元测试 tests/unit/memory/test_storage.py（同文件追加）：
      两个不同 tenant_id 使用相同 session_id 各自追加消息，各自读取只见自己的数据
      （验收场景 US1-3，SC-002）
- [ ] T011 [P] [US1] 并发 append 单元测试 tests/unit/memory/test_storage.py（同文件追加）：
      对同一 (tenant_id, session_id) 并发发起多个 append（asyncio.gather），验证全部消息
      均被写入（不丢失）、seq 连续不重复不跳号、读取顺序与实际写入的事务顺序一致
      （spec Edge Cases 第 3 条，research.md R3 并发保护）

**Checkpoint**: US1 测试全绿——MVP 可演示（真实 SQLite 持久化读写）

---

## Phase 4: User Story 2 - 超出上下文预算时自动压缩历史 (Priority: P2)

**Goal**: 累计 token 超预算时自动触发压缩，保留窗口内消息不变，压缩失败不丢数据

**Independent Test**: 用 stub provider 追加消息使累计 token 超出测试预算，
验证压缩后早期消息替换为摘要、保留窗口消息不变、总 token 回落预算内

- [ ] T012 [US2] 实现压缩判定与执行 src/kernel/memory/compaction.py：
      estimate_tokens（复用 001 R9 的字符数/4 粗估策略）、决定 to_compact/to_keep
      划分（保留最近 keep_recent_messages 条，to_compact 为空则跳过压缩，research.md R5）、
      build_summary_request（构造 system 提示要求第三人称简洁摘要）、
      compact_if_needed(rows, budget, provider, model) → 若需要压缩：调用
      provider.complete() 生成摘要 → 调用方在同一 SQLite 事务内 replace_rows（状态机见 data-model.md）
- [ ] T013 [US2] 在 src/kernel/memory/__init__.py 的 SqliteMemory.load()/append() 中
      集成压缩：读取全部消息后调用 compact_if_needed；provider 调用失败时（ProviderError
      子类）原样上抛，事务未开始因而原始数据不受影响（FR-007，research.md R5 原子性）；
      append 与 load 共用同一压缩私有方法（FR-004，research.md R6）
- [ ] T014 [P] [US2] 自动压缩单元测试 tests/unit/memory/test_compaction.py：
      追加消息使累计 token 超出一个较小的测试预算 → 触发压缩，早期消息被替换为摘要、
      保留窗口内消息不变、再次读取总 token 数不超预算（验收场景 US2-1/2，SC-003）
- [ ] T015 [P] [US2] 未超预算与边界单元测试 tests/unit/memory/test_compaction.py（同文件追加）：
      累计 token 未超预算时不触发压缩、消息原样保留（验收场景 US2-3）；
      to_compact 为空（所有消息在保留窗口内但仍超预算）时跳过压缩，不报错（Edge Case）
- [ ] T016 [P] [US2] 压缩失败容错单元测试 tests/unit/memory/test_compaction.py（同文件追加）：
      stub provider 配置为抛 CallTimeoutError（复用 001 stub 机制）→ append/load 原样上抛该异常，
      原始消息未被删除、下次读取仍是压缩前的完整历史（验收场景 US2-4，FR-007）

**Checkpoint**: US1+US2 测试全绿——压缩能力完整且失败安全

---

## Phase 5: User Story 3 - 存取操作可观测 (Priority: P3)

**Goal**: 每次 load/append 产生带 session/tenant 标注的 span，压缩事件可识别

**Independent Test**: InMemorySpanExporter 采集一次触发压缩的 append 流程，
断言 span 属性含 tenant_id/session_id/compaction_triggered，且压缩内部的
provider 调用 span 为其子 span

- [ ] T017 [US3] 实现操作遥测 src/kernel/memory/telemetry.py：memory_operation_span
      (operation, session_id, tenant_id) 上下文管理器，span name="memory.{operation}"，
      复用 kernel.provider 的 tracer（与 002 react.step 同一套 tracer，research.md R7）、
      可后补 compaction_triggered 属性、遥测异常 try/except 不影响调用（沿用 001/002 容错模式）
- [ ] T018 [US3] 在 src/kernel/memory/__init__.py 集成遥测：load()/append() 全程经
      memory_operation_span 包裹（压缩的 provider 调用需在 span 内发起以形成父子关系，
      同 002 R5 模式），压缩完成后设置 compaction_triggered=True/False（FR-008，data-model.md span 契约）
- [ ] T019 [US3] 遥测单元测试 tests/unit/memory/test_memory_telemetry.py：
      普通读写操作 span 属性含 tenant_id/session_id/compaction_triggered=False（验收场景 US3-1）；
      触发压缩的操作 span 的 compaction_triggered=True，且其内 chat 子 span 的 parent.span_id
      等于该 memory span 的 context.span_id（而非仅数量匹配，参照 002 A1 的经验）（验收场景 US3-2）；
      注入抛异常的 span 处理不影响读写/压缩结果（验收场景 US3-3，FR-009）

**Checkpoint**: 全部用户故事测试独立全绿

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 演示脚本、文档收尾与最终验证

- [ ] T020 [P] 创建演示脚本 examples/demo_memory_stub.py：真实临时 SQLite 文件 +
      脚本化 stub provider + ConsoleSpanExporter，依次演示持久化读写/跨租户隔离/
      自动压缩三个场景并打印 span（quickstart.md 第 2 节的预期输出）
- [ ] T021 按 quickstart.md 全流程验证：pytest tests/unit/memory 全绿（SC-001/SC-005）→
      demo_memory_stub 输出符合预期（SC-002/003/004）→ 计时确认 15 分钟内完成，修复发现的问题
- [ ] T022 更新 README.md roadmap：003 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1 → US2 → US3**：US1 建立存储层是 US2/US3 的前提；US2/US3 均需要
  SqliteMemory 骨架已存在（T008），US2 补全压缩逻辑，US3 织入遥测——
  两者都改动 `__init__.py` 但改动点不同（压缩逻辑 vs span 包裹），
  US3 需等 US2 完成后再开工以避免重复改动同一批代码
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T005、T006 并行（T004 先行）
- US1 内：T009、T010、T011 同文件但断言独立，可并行准备后顺序追加
- US2 内：T014/T015/T016 同文件但断言独立，可并行准备后顺序追加
- Phase 6：T020 与 T021 顺序（T021 依赖 T020 产出的脚本）

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T011）：真实 SQLite 持久化读写 + 跨租户隔离 +
并发安全即可演示核心价值。随后 US2（压缩）→ US3（遥测）递增交付。每个 Checkpoint 处
`pytest` 必须全绿再前进。
