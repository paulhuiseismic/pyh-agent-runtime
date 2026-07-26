---

description: "Task list for 长期记忆"
---

# Tasks: 长期记忆

**Input**: Design documents from `/specs/004-long-term-memory/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`kernel.provider`）、003（`aiosqlite`、SQLite 测试基础设施模式）

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试（FR-009），
不适用模板的"测试可选"约定。

**Organization**: 按用户故事分组；US1（提炼+写入）与 US2（查询）相对独立
（分别落在 storage 的写/读路径），US3（冲突处理）验证的是 US1 写入路径的
既有 upsert 行为，不新增生产代码，只新增测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

延续 001/002/003 的单包 library 布局：`src/kernel/memory/`、`tests/unit/memory/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 无新增依赖，仅确认目录结构

- [ ] T001 确认 tests/unit/memory/ 目录已存在（003 已创建，无需新建）

**Checkpoint**: `pytest tests/unit/memory -q` 可运行（复用 003 已有测试全绿基线）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据结构与提炼解析——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [ ] T002 实现数据结构 src/kernel/memory/long_term_models.py：frozen dataclass
      MemoryEntry（content/category，category 可为 None）、ExtractionResult
      （entries: list[MemoryEntry]）（data-model.md）
- [ ] T003 [P] 实现提炼提示构造与解析 src/kernel/memory/extraction.py：
      build_extraction_request(history, *, tenant_id, model) 构造要求 JSON 数组输出的
      system 提示（research.md R1）；parse_extraction(content) 解析
      [{"category": str|null, "content": str}, ...] → 非法 JSON/元素缺 content 时
      返回 ExtractionResult(entries=[])（research.md R2，不抛异常）；category 为
      空字符串或全空白时归一化为 None（data-model.md，避免误判为同一类别）
- [ ] T004 [P] 数据结构与解析单元测试 tests/unit/memory/test_long_term_models.py,
      tests/unit/memory/test_extraction.py：MemoryEntry/ExtractionResult 构造正确；
      parse_extraction 对合法数组（含 category=null 元素）、非 JSON、非数组、
      元素缺 content 均返回预期结果（含空数组场景）；category="" 或 "   " 均被
      归一化为 None（不作为真实类别参与后续 UNIQUE 约束）

**Checkpoint**: `pytest tests/unit/memory/test_long_term_models.py tests/unit/memory/test_extraction.py` 全绿

---

## Phase 3: User Story 1 - 从一次对话中提炼长期记忆 (Priority: P1) 🎯 MVP

**Goal**: 显式触发提炼，经 provider 调用产出记忆条目并原子写入；空结果/失败均不写脏数据

**Independent Test**: stub provider 返回预设提炼结果，调用 extract()，
验证写入的记忆条目符合预期，全程无平台组件、无真实模型

- [ ] T005 [US1] 实现存储层写入 src/kernel/memory/long_term_storage.py：
      LongTermStore 类——建表 memory_entries（UNIQUE(tenant_id, category)，
      data-model.md 表结构）、upsert_entries(tenant_id, entries) 用
      INSERT ... ON CONFLICT(tenant_id, category) DO UPDATE 原子写入
      （research.md R3，复用 003 storage.py 的 asyncio.Lock 写序列化模式避免
      并发连接初始化竞态）、close()
- [ ] T006 [US1] 实现 LongTermMemory.extract() src/kernel/memory/long_term.py：
      __init__(db_path, provider, model)；extract(history, *, tenant_id) 的
      空 history 直接返回空结果、构造提炼请求调用 provider.complete()、
      provider 异常原样上抛（FR-005）、解析结果非空时调用 upsert_entries
      （状态机见 data-model.md）
- [ ] T007 [US1] 包级导出 src/kernel/memory/__init__.py 追加：按
      contracts/long-term-memory-api.md 导出 LongTermMemory、MemoryEntry、
      ExtractionResult（在 003 已有导出基础上追加，不修改既有导出项）
- [ ] T008 [P] [US1] 提炼写入单元测试 tests/unit/memory/test_long_term_extract.py：
      含偏好陈述的历史提炼后条目被写入（验收场景 US1-1）；不含值得记住内容的历史
      提炼后不写入任何条目（验收场景 US1-2，FR-004）；空 history 不发起 provider 调用
      直接返回空结果（Edge Case）
- [ ] T009 [P] [US1] 提炼失败容错单元测试 tests/unit/memory/test_long_term_extract.py
      （同文件追加）：stub provider 配置为抛 CallTimeoutError（复用 001 stub 机制）→
      extract 原样上抛该异常，长期记忆库中无任何条目写入（验收场景 US1-3，SC-005）
- [ ] T010 [P] [US1] 并发提炼单元测试 tests/unit/memory/test_long_term_extract.py
      （同文件追加）：同一 tenant_id 并发触发多次 extract（asyncio.gather），
      各自产生不同 category 的记忆条目，验证全部条目均写入、不丢失、不误覆盖
      彼此的正常新增（spec Edge Cases 第 3 条，复用 003 storage.py 的写锁序列化
      保证，research.md R3）

**Checkpoint**: US1 测试全绿——MVP 可演示（stub 下一次完整提炼写入）

---

## Phase 4: User Story 2 - 查询与当前对话相关的长期记忆 (Priority: P2)

**Goal**: 按租户查询记忆条目，时间倒序、数量上限、跨租户隔离

**Independent Test**: 预先写入若干条记忆，调用 query()，验证排序、数量上限、
跨租户隔离均符合预期

- [ ] T011 [US2] 实现存储层查询 src/kernel/memory/long_term_storage.py 追加：
      query_entries(tenant_id, limit) 执行
      SELECT content, category FROM memory_entries WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?
      （data-model.md）
- [ ] T012 [US2] 实现 LongTermMemory.query() src/kernel/memory/long_term.py 追加：
      校验 limit 为正整数（非正数在查询前抛 InvalidRequestError，FR-006）、
      调用 query_entries 并转换为 list[MemoryEntry]
- [ ] T013 [P] [US2] 查询排序与上限单元测试 tests/unit/memory/test_long_term_query.py：
      写入多条记忆后查询，验证按写入时间倒序、数量不超过 limit（验收场景 US2-1）；
      空库查询返回空列表不报错（验收场景 US2-2）；limit=0/-1 在查询前拒绝（Edge Case）
- [ ] T014 [P] [US2] 跨租户隔离单元测试 tests/unit/memory/test_long_term_query.py
      （同文件追加）：两个不同 tenant_id 各自写入记忆后查询，各自只见自己的条目
      （验收场景 US2-3，SC-002）

**Checkpoint**: US1+US2 测试全绿——提炼与查询能力完整

---

## Phase 5: User Story 3 - 新记忆与已有记忆冲突时的处理 (Priority: P3)

**Goal**: 验证同类别覆盖、不同类别独立新增、反复提炼不无限增长
（生产代码已在 T005 的 upsert_entries 实现，本阶段仅补测试）

**Independent Test**: 连续两次提炼产生同类别记忆，验证库中该类别仅保留一条

- [ ] T015 [P] [US3] 同类别覆盖单元测试 tests/unit/memory/test_long_term_conflict.py：
      两次提炼产生同一 category 的不同 content，第二次写入后查询该类别仅一条且为
      最新内容（验收场景 US3-1，SC-003）
- [ ] T016 [P] [US3] 不同类别独立与无法判定类别单元测试
      tests/unit/memory/test_long_term_conflict.py（同文件追加）：不同 category
      的记忆各自独立存在、互不影响（验收场景 US3-2）；category=None 的多次提炼
      各自独立新增，不与任何已有记录冲突（Edge Case，research.md R3 的 NULL 语义）
- [ ] T017 [P] [US3] 反复提炼不无限增长单元测试
      tests/unit/memory/test_long_term_conflict.py（同文件追加）：对同一租户/
      同一类别连续提炼 N 次（N≥3），验证该类别记录数始终为 1（验收场景 US3-3）

**Checkpoint**: US1-US3 测试全绿——冲突处理验证完整

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 遥测、演示脚本、文档收尾与最终验证

- [ ] T018 [P] 实现操作遥测 src/kernel/memory/telemetry.py 追加：
      long_term_memory_span(operation, tenant_id) 上下文管理器，span
      name="long_term_memory.{operation}"，复用 kernel.provider 的 tracer
      （research.md R5），遥测异常 try/except 不影响调用
- [ ] T019 在 src/kernel/memory/long_term.py 集成遥测：extract()/query() 全程经
      long_term_memory_span 包裹（extract 内的 provider 调用需在 span 内发起以
      形成父子关系，同 002/003 模式）（FR-011，data-model.md span 契约）
- [ ] T020 [P] 遥测单元测试 tests/unit/memory/test_long_term_telemetry.py：
      extract/query 操作 span 属性含 tenant_id/operation（SC-004）；extract 触发的
      span 下 chat 子 span 的 parent.span_id 等于该 span 的 context.span_id
      （参照 002/003 的父子 span 断言经验）；注入抛异常的 span 处理不影响操作结果
- [ ] T021 [P] 创建演示脚本 examples/demo_long_term_memory_stub.py：脚本化 stub
      provider + ConsoleSpanExporter，依次演示提炼写入/查询/同类别覆盖/跨租户隔离
      四个场景并打印 span（quickstart.md 第 2 节的预期输出）
- [ ] T022 按 quickstart.md 全流程验证：pytest 全绿（SC-001）→ demo 输出符合预期
      （SC-002/003/004）→ 计时确认 15 分钟内完成，修复发现的问题
- [ ] T023 更新 README.md roadmap：004 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1 → US2**：US2 的查询依赖 US1 已建立的写入路径产出可查询的数据
  （测试层面 US2 可独立准备 fixture 数据，不强依赖 US1 的具体实现细节）
- **US3**：依赖 US1 的 upsert_entries 已实现（T005），US3 只新增测试文件，
  可与 US2 并行开工
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T003 与 T002 并行，T004 随后
- US1 内：T008、T009、T010 同文件但断言独立，可并行准备后顺序追加
- US2 内：T013、T014 同文件但断言独立，可并行准备后顺序追加
- 跨故事：US3（T015-T017）可与 US2（T011-T014）并行开工（均依赖 US1 的 T005，
  互不依赖对方）
- Phase 6：T018/T021 可并行，T019 依赖 T018，T020 依赖 T019，T022 依赖 T021

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T010）：stub 下跑通一次完整"提炼→写入"
（含并发安全）即可演示核心价值。随后 US2（查询）与 US3（冲突验证）可并行推进，
最后 Polish 补齐遥测与演示脚本。每个 Checkpoint 处 `pytest` 必须全绿再前进。
