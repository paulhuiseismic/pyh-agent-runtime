# Feature Specification: 内核骨架与 provider 模块

**Feature Branch**: `001-kernel-provider`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "内核骨架与 provider 模块：建立 agent 内核四模块（provider/react/memory/tool）的项目骨架与接口定义，并完整实现 provider 模块。provider 通过独立部署的 LiteLLM proxy（OpenAI 兼容 HTTP 接口）完成 LLM 调用与多模型路由，不直接对接各模型厂商 SDK。每次 LLM 调用必须：设置显式超时；设置 token 上限与成本上限，超限明确失败；发出符合 OTel GenAI 语义约定的 span，且必须携带 tenant_id 属性。provider 支持统一的请求/响应结构，模型选择由调用方以参数传入。内核不依赖任何平台层组件，可独立单元测试；provider 模块必须附带单元测试。同时创建 THIRD_PARTY.md 并登记 LiteLLM。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 通过 provider 完成一次受保护的 LLM 调用 (Priority: P1)

作为内核的上层调用方（后续的 react 模块或平台层开发者），我可以构造一个统一格式的
LLM 请求（指定模型、消息、租户标识、限额配置），通过 provider 发起调用，
调用经统一路由入口转发到目标模型，并返回统一格式的响应（内容、token 用量、成本）。

**Why this priority**: 这是整个 runtime 的最小可验证核心——没有一次可靠的 LLM
调用，其余一切能力都无从构建。

**Independent Test**: 使用本地 stub 模拟路由端点，构造请求并调用 provider，
验证返回的响应结构完整（内容、用量、成本），全程不需要任何平台层组件或真实模型密钥。

**Acceptance Scenarios**:

1. **Given** 路由端点可用且请求参数完整, **When** 调用方发起一次 LLM 调用,
   **Then** 收到统一结构的成功响应，包含模型输出内容、token 用量与本次调用成本。
2. **Given** 调用方在请求中指定了不同的模型名, **When** 发起调用,
   **Then** 请求被转发到对应模型，响应中标明实际使用的模型。
3. **Given** 请求缺少租户标识, **When** 发起调用,
   **Then** 调用被拒绝并返回明确的参数错误，不会发出任何对外请求。

---

### User Story 2 - 超时与超限调用明确失败 (Priority: P2)

作为调用方，当一次 LLM 调用超过显式超时时间、超出 token 上限或成本上限时，
我会收到类型明确、可区分的失败结果，而不是无限等待或静默截断。

**Why this priority**: 多租户 runtime 的核心风险是单次失控调用拖垮全局；
限额保护是宪法级的强制要求（原则 IV），必须与调用能力同期交付。

**Independent Test**: 用 stub 模拟慢响应、超长响应和高成本响应三种场景，
分别验证 provider 在超时、token 超限、成本超限时返回对应的明确错误类型。

**Acceptance Scenarios**:

1. **Given** 路由端点响应时间超过请求设定的超时, **When** 发起调用,
   **Then** 调用在超时时间内终止并返回"超时"类型的失败结果。
2. **Given** 请求设定了 token 上限, **When** 本次调用的 token 用量将超出上限,
   **Then** 调用返回"token 超限"类型的失败结果，且失败信息包含实际用量与上限值。
3. **Given** 请求设定了成本上限, **When** 本次调用的成本超出上限,
   **Then** 调用返回"成本超限"类型的失败结果，且失败信息包含实际成本与上限值。
4. **Given** 调用方未显式提供超时或限额, **When** 构造请求,
   **Then** 请求自动采用系统内置的安全默认值，任何限额都不允许为"无限制"。

---

### User Story 3 - 每次调用可按租户追溯 (Priority: P3)

作为运维/审计人员，每一次 LLM 调用（无论成功或失败）都会产生一条符合行业
GenAI 遥测语义约定的调用记录（span），且必带租户标识属性，
我可以按租户维度追溯任意一次调用的模型、用量、成本与结果。

**Why this priority**: 可观测性是宪法强制要求（原则 V），也是后续审计与成本
核算能力的数据基础；但它不阻塞调用能力本身的验证，故列为 P3。

**Independent Test**: 使用内存型遥测采集器运行调用（成功、超时、超限各一次），
验证每次调用均产生一条 span，属性中包含租户标识、模型名、token 用量与调用结果。

**Acceptance Scenarios**:

1. **Given** 一次成功的 LLM 调用, **When** 调用完成,
   **Then** 产生一条符合 GenAI 语义约定的 span，携带租户标识、模型名、
   token 用量、成本与成功状态。
2. **Given** 一次失败的调用（超时或超限）, **When** 调用终止,
   **Then** 仍产生一条 span，状态标记为失败并注明失败类型。
3. **Given** 遥测后端不可用, **When** 发起调用,
   **Then** 调用本身正常执行，遥测缺失不影响业务结果。

---

### User Story 4 - 内核骨架可独立演进 (Priority: P4)

作为内核开发者，我可以在完全不启动平台层组件的情况下，实例化内核四模块
（provider/react/memory/tool）的接口骨架并运行全部单元测试；
react/memory/tool 三个模块在本 feature 中只有接口定义与占位实现。

**Why this priority**: 骨架为后续 feature（react、memory、tool 实现）预留
稳定的接口边界，是宪法原则 I 的落地形态，但本身不交付终端可用能力。

**Independent Test**: 在无任何平台组件、无网络依赖的环境下运行全部单元测试并通过。

**Acceptance Scenarios**:

1. **Given** 一个仅包含内核的干净环境, **When** 运行全部单元测试,
   **Then** 测试全部通过，过程中不需要平台层组件、真实模型密钥或外部网络。
2. **Given** 内核四模块的接口定义, **When** 检查模块间依赖关系,
   **Then** 不存在任何内核模块对平台层的依赖。

---

### Edge Cases

- 路由端点完全不可达（网络拒绝/DNS 失败）时，provider 返回"连接失败"类型错误，
  不做无限重试。
- 调用方传入非法限额（负数、零超时）时，请求在发出前被参数校验拒绝。
- 路由端点返回非预期格式的响应（缺少用量字段等）时，provider 返回
  "响应格式错误"类型错误，而不是抛出未分类异常。
- 同一进程内并发发起多次调用时，各调用的超时、限额与 span 互不串扰。
- 模型单价未配置时，成本无法计算——调用被拒绝（宪法要求成本上限必须生效，
  无单价即无法执行成本控制）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: provider MUST 提供统一的请求结构（消息列表、模型名、租户标识、
  超时、token 上限、成本上限）与统一的响应结构（输出内容、实际模型、
  token 用量、成本、结束原因）。
- **FR-002**: 模型选择 MUST 由调用方以参数显式传入；provider 内部
  MUST NOT 包含任何租户到模型的映射逻辑（该策略属于平台层）。
- **FR-003**: provider MUST 通过统一的模型路由入口（OpenAI 兼容 HTTP 接口的
  独立路由服务）完成所有 LLM 调用，MUST NOT 直接对接任何模型厂商的专有 SDK。
- **FR-004**: 每次调用 MUST 应用显式超时；调用方未指定时 MUST 采用安全默认值；
  "无限制"MUST NOT 作为任何限额的可选值或默认值。
- **FR-005**: 每次调用 MUST 应用 token 上限与成本上限；超限时 MUST 返回
  类型明确、可编程区分的失败结果（超时/token 超限/成本超限/连接失败/格式错误），
  MUST NOT 静默截断或静默继续。
- **FR-006**: 每次调用（含失败）MUST 产生一条符合 OTel GenAI 语义约定的 span，
  且 MUST 携带 `tenant_id` 属性；请求缺少租户标识时 MUST 在发出前拒绝。
- **FR-007**: 遥测发送失败 MUST NOT 影响调用本身的执行与结果。
- **FR-008**: 内核 MUST 包含 provider/react/memory/tool 四模块的接口定义；
  react/memory/tool 在本 feature 中为接口与占位实现；内核任何模块
  MUST NOT 依赖平台层组件。
- **FR-009**: provider 模块 MUST 附带单元测试，覆盖成功调用、三类超限失败、
  参数校验、span 发出六类场景；测试 MUST 以本地 stub/mock 方式模拟路由端点，
  MUST NOT 依赖真实模型服务。
- **FR-010**: 仓库根目录 MUST 创建 `THIRD_PARTY.md` 并登记本 feature 引入的
  第三方组件及其 license（LiteLLM — MIT，仅使用核心功能，
  不使用 enterprise 目录下的商业功能）。

### Key Entities

- **LLM 请求**: 一次调用的完整输入——消息列表、目标模型名、租户标识、
  超时、token 上限、成本上限。
- **LLM 响应**: 一次成功调用的输出——内容、实际模型、token 用量（输入/输出）、
  成本、结束原因。
- **调用失败结果**: 类型化的失败——超时、token 超限、成本超限、连接失败、
  响应格式错误、参数错误，各自携带诊断信息。
- **限额配置**: 超时、token 上限、成本上限的取值与安全默认值；
  含模型单价表（用于成本计算）。
- **调用遥测记录（span）**: 每次调用产生的观测数据——租户标识、模型、用量、
  成本、耗时、结果状态。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在无平台层组件、无外部网络、无真实模型密钥的环境中，
  内核全部单元测试可一次性通过。
- **SC-002**: 100% 的 LLM 调用（含失败调用）产生带租户标识的遥测记录，
  抽查任意一次调用可定位到其租户、模型、用量与成本。
- **SC-003**: 100% 的超时/超限场景返回类型明确的失败结果：调用在设定超时的
  1.5 倍时间内必然终止，超限失败信息均包含实际值与上限值。
- **SC-004**: 新开发者按文档在 15 分钟内可用本地 stub 跑通一次完整的
  provider 调用（含查看遥测输出）。
- **SC-005**: 内核模块对平台层的依赖数为 0（可通过依赖检查验证）。

## Assumptions

- 本 feature 仅支持非流式（一次性返回）调用；流式输出作为后续 feature，
  不在本次范围。
- 成本计算基于限额配置中的模型单价表（每千 token 输入/输出单价）在本地完成；
  单价未配置的模型不允许调用。
- token 上限的执行方式：请求侧将上限传递给模型（作为最大输出限制），
  响应侧校验实际总用量，两侧任一超限即判定失败。
- 安全默认值采用保守取值（如超时 60 秒、单次调用成本上限一个较低金额），
  具体数值在 plan 阶段确定，全部可配置。
- 路由服务（LiteLLM proxy）的部署与配置属于开发环境准备工作，
  本 feature 交付本地 stub 与对接契约，不交付 proxy 的生产部署方案。
- 租户标识在本 feature 中是调用方传入的不透明字符串，
  其签发与校验属于平台层，不在本次范围。
- 工具的沙箱执行属于后续 feature（004 plugin tool + sandbox）；
  本 feature 的 Tool 接口仅定义调用签名，不含沙箱语义，
  沙箱作为 `invoke()` 背后的执行环境实现，不改变接口契约。
