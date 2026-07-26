# Feature Specification: memory 压缩与上下文管理

**Feature Branch**: `003-memory-compression`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "memory 压缩与上下文管理：实现内核 memory 模块的完整会话上下文管理，
替换 001 中的 NoopMemory 占位实现。memory 按 session_id 持久化保存对话消息，支持 load 与 append
两个操作，所有操作必带 tenant_id 作为隔离键，不同租户的会话数据互不可见。当某个会话的历史消息
累计 token 数超过可配置的上下文预算时，memory 必须自动压缩：将较早的消息通过一次 LLM 调用压缩为
一段摘要，替换掉被压缩的原始消息，同时保留最近若干条消息不被压缩。压缩必须自动触发，调用方不需要
手动调用压缩操作。压缩本身作为一次 LLM 调用，天然继承 provider 已有的超时/token/成本上限与 span；
memory 自身的存取操作也需要发出可观测记录。默认持久化实现使用 SQLite（WAL 模式）。memory 不依赖
任何平台层组件，可独立单元测试。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 会话消息的持久化读写 (Priority: P1)

作为内核的上层调用方（未来的 react 模块或平台层），我可以为一个会话追加消息、
读取该会话迄今为止的完整历史，跨进程重启后历史依然存在；不同租户即使使用
相同的 session_id，各自的会话数据也完全隔离、互不可见。

**Why this priority**: 这是 memory 模块存在的最基本价值——没有可靠的持久化
读写，压缩能力无从谈起，也无法支撑任何需要多轮对话记忆的场景。

**Independent Test**: 用真实的本地存储（临时数据库文件）追加若干条消息、
重新打开一次连接后读取，验证消息顺序与内容完整；用两个不同 tenant_id
写入相同 session_id，验证互不可见。

**Acceptance Scenarios**:

1. **Given** 一个新会话, **When** 依次追加 3 条消息, **Then** 读取该会话返回
   这 3 条消息，顺序与追加顺序一致。
2. **Given** 已持久化的会话数据, **When** 进程重启后用相同存储位置重新读取,
   **Then** 历史消息完整保留。
3. **Given** 两个不同租户使用相同的 session_id 各自追加了消息, **When**
   分别以各自 tenant_id 读取该 session_id, **Then** 各自只能看到自己
   追加的消息，看不到对方的数据。
4. **Given** 一个不存在的 session_id, **When** 读取该会话, **Then** 返回空历史
   （不报错，视为全新会话）。

---

### User Story 2 - 超出上下文预算时自动压缩历史 (Priority: P2)

作为调用方，当某个会话的历史消息累计 token 数超过配置的预算时，我不需要
做任何额外操作——memory 会自动把较早的消息压缩为一段摘要，同时保留最近的
若干条消息不被压缩，使后续读取到的历史仍然在预算之内，且保留了早期对话的
关键信息。

**Why this priority**: 这是 feature 的核心差异化价值（"压缩"二字），但依赖
User Story 1 的读写能力已经建立，故列为第二优先级。

**Independent Test**: 用 stub provider 追加足够多的消息使累计 token 超出一个
较小的测试预算，验证触发压缩后：早期消息被替换为一条摘要消息、最近若干条
消息原样保留、读取到的历史总 token 数回落到预算之内。

**Acceptance Scenarios**:

1. **Given** 一个会话的历史消息累计 token 数超过配置的上下文预算, **When**
   追加下一条消息或读取该会话, **Then** memory 自动触发一次压缩：较早的
   消息被替换为一条摘要消息，最近若干条消息保持原样不变。
2. **Given** 压缩已完成, **When** 再次读取该会话, **Then** 返回的历史包含
   摘要消息 + 保留的最近消息，总 token 数不超过配置的预算。
3. **Given** 历史消息累计 token 数尚未超过预算, **When** 追加消息或读取,
   **Then** 不触发压缩，历史消息原样保留。
4. **Given** 压缩所需的 LLM 调用本身失败（超时/超限等 provider 已定义的
   类型化异常）, **When** 触发压缩的操作执行, **Then** 该次操作失败并
   原样上抛该异常，原始历史消息不被破坏（压缩失败不应导致数据丢失）。

---

### User Story 3 - 存取操作可观测 (Priority: P3)

作为运维/审计人员，每一次 memory 的读写操作以及每一次自动触发的压缩，
都会产生可关联到会话与租户的遥测记录，使我可以追溯某个会话的历史演变
（何时压缩、压缩前后的消息量变化）。

**Why this priority**: 可观测性是宪法强制要求，但属于对已有读写/压缩能力的
增强，不阻塞核心功能，故列为第三优先级。

**Independent Test**: 用内存型遥测采集器执行一次"追加消息触发压缩"的完整
流程，验证产生的记录包含会话标识、租户标识、以及"发生了压缩"的标注；
同时验证压缩内部发起的 LLM 调用仍带有 provider 自有的完整遥测（继承自 001）。

**Acceptance Scenarios**:

1. **Given** 一次 append 或 load 操作, **When** 操作完成, **Then** 产生一条
   携带 session_id 与 tenant_id 的遥测记录。
2. **Given** 一次操作触发了自动压缩, **When** 压缩完成, **Then** 遥测记录中
   可识别出"本次操作发生了压缩"，且压缩内部的 LLM 调用产生 provider 自带的
   GenAI span（tenant_id 透传，继承自 001）。
3. **Given** 遥测后端不可用, **When** 执行任意 memory 操作, **Then** 操作本身
   正常完成，遥测缺失不影响读写或压缩结果。

---

### Edge Cases

- 单条消息本身的 token 数就超过整个上下文预算（如一条超长消息）时，
  该消息不会被压缩掉（压缩只处理"较早的消息"，保留策略覆盖的最近消息
  不参与压缩），但会被计入总量——此时压缩后总 token 数仍可能超预算，
  这种情况按"尽力压缩"处理，不视为错误，但需要能被观测到。
- 需要压缩的"较早消息"集合为空（例如所有消息都在"最近保留窗口"内，
  但总量依然超预算）时，不发起压缩调用，按上一条同样处理。
- 并发对同一 session_id 执行 append 时，消息顺序与压缩判定必须保持一致，
  不能因并发写入导致消息丢失或重复压缩。
- 压缩产生的摘要消息本身也计入下一次的 token 预算判定，可能被再次压缩
  （多轮压缩），不需要特殊处理，与首次压缩走相同逻辑。
- 存储文件不可写（磁盘只读/权限问题）时，操作失败并返回明确的错误，
  不静默丢弃数据。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: memory MUST 按 `session_id` 持久化保存消息序列，持久化数据
  MUST 在进程重启后依然可读。
- **FR-002**: memory 的 `load` 与 `append` 操作 MUST 携带 `tenant_id`；
  不同 `tenant_id` 下相同 `session_id` 的数据 MUST 完全隔离，任一方
  MUST NOT 能读取到另一方的数据。
- **FR-003**: `load` 对不存在的 `session_id` MUST 返回空历史，MUST NOT 报错。
- **FR-004**: memory MUST 支持可配置的上下文 token 预算与"最近保留消息数"
  两项配置；当某会话历史的累计 token 数超过预算时，MUST 自动触发压缩，
  MUST NOT 需要调用方显式调用压缩操作。
- **FR-005**: 压缩 MUST 将超出"最近保留窗口"的较早消息，通过一次 provider
  LLM 调用生成一段摘要，并用该摘要消息替换被压缩的原始消息；
  "最近保留窗口"内的消息 MUST NOT 被压缩。
- **FR-006**: 压缩发起的 LLM 调用 MUST 通过 provider 完成，因而自动获得
  provider 已有的超时、token/成本上限与 GenAI span（继承自 001，不重复实现）。
- **FR-007**: 压缩所需的 LLM 调用失败时（provider 抛出的类型化异常），
  触发该次压缩的 `load`/`append` 操作 MUST 以该异常原样终止，
  MUST NOT 丢失或破坏原始历史消息。
- **FR-008**: memory 的每次 `load`/`append` 操作 MUST 产生可关联到
  `session_id` 与 `tenant_id` 的遥测记录；发生压缩时 MUST 能从遥测中
  识别出"本次操作发生了压缩"。
- **FR-009**: 遥测发送失败 MUST NOT 影响 memory 操作本身的执行与结果
  （延续 001/002 的遥测容错要求）。
- **FR-010**: memory 模块 MUST NOT 依赖任何平台层组件；单元测试 MUST 使用
  真实的本地存储（临时文件）与 stub provider，MUST NOT 依赖真实模型服务
  或平台层基础设施。
- **FR-011**: memory 实现 MUST 替换 001 中的 `NoopMemory` 占位实现，
  但 MUST NOT 改变 001 已冻结的 `Memory` Protocol 签名
  （`load(session_id, *, tenant_id)` / `append(session_id, message, *, tenant_id)`）。
- **FR-012**: 默认持久化实现 MUST 使用 SQLite；存储实现 MUST 通过 001
  已定义的 `Memory` 接口注入，MUST NOT 与内核其余模块（provider/react/tool）
  产生新的跨层依赖（memory 对 provider 的依赖仅限于压缩时发起 LLM 调用，
  与 001/002 中"内核内部依赖"的既有模式一致）。

### Key Entities

- **会话历史**: 某个 `(tenant_id, session_id)` 组合下的完整消息序列
  （持久化存储的核心数据）。
- **上下文预算配置**: 触发压缩的 token 数阈值、"最近保留消息数"，
  均为可配置项且有安全默认值。
- **摘要消息**: 压缩产生的、替换一批原始消息的单条消息，参与后续的
  token 预算判定与再次压缩。
- **memory 操作遥测记录**: 每次 `load`/`append` 产生的观测数据——
  会话标识、租户标识、是否发生压缩。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在无平台层组件、无真实模型服务的条件下，memory 模块全部
  单元测试可一次性通过。
- **SC-002**: 100% 的跨租户读取尝试均被隔离——相同 `session_id` 下不同
  `tenant_id` 的数据互不可见。
- **SC-003**: 100% 触发压缩的场景中，压缩完成后再次读取的历史总 token 数
  回落到配置预算之内（除单条超长消息等 Edge Case 外）。
- **SC-004**: 100% 的 `load`/`append` 操作产生可按会话与租户追溯的遥测记录，
  抽查任意一次触发压缩的操作可识别出压缩发生。
- **SC-005**: 持久化数据在进程重启后 100% 可完整恢复（不丢失、不错序）。

## Assumptions

- 摘要生成的具体提示词与压缩策略（如何决定摘要的详细程度）留待 plan 阶段
  确定技术实现，本 spec 只约束行为契约：较早消息 → 一次 LLM 调用 → 一条
  摘要消息，替换被压缩的原始消息。
- "最近保留消息数"与"上下文预算"两项配置的具体默认值留待 plan 阶段确定，
  但两者均 MUST 有安全默认值（不允许"不压缩"作为默认行为，呼应宪法
  "任何限额不允许无限制"的精神——这里体现为"预算不能是无穷大"）。
- 本 feature 不支持删除会话、不支持导出/导入会话数据；这些管理类操作
  留给未来可能的平台层能力，不在本次范围。
- 压缩是单向操作：被压缩的原始消息一旦替换为摘要即不可逆恢复原文，
  调用方如需保留完整原始记录需自行在其他层面归档（不在本 feature 范围）。
- 并发写入保护（Edge Cases 中"并发 append 顺序一致"）在 plan 阶段选择
  与 SQLite 特性匹配的技术方案实现，不引入额外的分布式锁组件（呼应
  宪法"最简实现优先"）。
