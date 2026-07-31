# Feature Specification: MCP 客户端接入

**Feature Branch**: `006-mcp-client-integration`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "006-mcp-client-integration: MCP 客户端接入——支持通过 stdio/HTTP 传输连接 MCP server，完成连接握手，通过 tools/list 发现远程工具，并将发现的 MCP 工具适配为 005 中已定义的 Tool Protocol，注册进 ToolRegistry，使其可直接被 ReAct 引擎（002）调用。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 接入本地 MCP server 并自动获得可用工具 (Priority: P1)

作为运行时的接入方，我配置一个通过子进程（stdio）方式启动的 MCP server，运行时完成与该
server 的连接握手，自动发现其提供的全部工具，并将这些工具注册为运行时内可调用的工具——
无需为每个 MCP server 手写适配代码。注册完成后，ReAct 引擎可以像调用本地工具/沙箱工具一样
调用这些工具，得到真实的执行结果。

**Why this priority**: 这是本 feature 的核心价值——让已有的 ReAct 引擎和工具体系可以直接
复用生态中大量已存在的 MCP server，而不需要为每个外部能力重新实现一个沙箱工具。没有这一步，
整个 MCP 接入没有意义。

**Independent Test**: 可通过启动一个已知返回固定工具列表和固定执行结果的测试用 MCP server
（stdio 子进程）独立验证：连接成功 → 工具出现在注册表中 → 调用工具返回预期结果。

**Acceptance Scenarios**:

1. **Given** 一个配置好的 stdio 型 MCP server 尚未连接，**When** 运行时发起连接，**Then**
   连接握手成功完成，且服务端与客户端协议版本被确认兼容。
2. **Given** 一个已连接的 MCP server 暴露了 N 个工具，**When** 运行时执行工具发现，**Then**
   这 N 个工具全部以「名称 + 描述 + 输入参数结构」的形式可在工具注册表中查到。
3. **Given** 一个已注册的 MCP 工具，**When** 调用方（如 ReAct 引擎）按 Tool 接口发起调用并
   传入合法参数，**Then** 调用透传给对应 MCP server 执行，并将其返回结果转换为调用方可读取
   的字符串结果。

---

### User Story 2 - 接入远程 MCP server（HTTP 传输） (Priority: P2)

作为运行时的接入方，除了本地子进程方式，我还希望连接部署在远程的 MCP server（通过 HTTP
传输），复用与 stdio 方式完全一致的发现与调用体验——对上层调用方（工具注册表、ReAct 引擎）
不感知底层是哪种传输方式。

**Why this priority**: 很多实用的 MCP server（如企业内部工具、SaaS 集成）以远程服务形式
提供而非本地子进程，若只支持 stdio，接入范围会被严重限制。但本地 stdio 场景（P1）已经能
验证核心适配逻辑与端到端价值，因此 HTTP 传输的优先级次之。

**Independent Test**: 可通过启动一个已知的、监听 HTTP 的测试用 MCP server 独立验证：连接
成功 → 工具发现 → 工具调用，行为与 stdio 场景下的验收标准完全对等。

**Acceptance Scenarios**:

1. **Given** 一个配置好的 HTTP 型 MCP server 地址，**When** 运行时发起连接，**Then** 连接
   握手成功完成，行为与 stdio 传输的握手结果等价。
2. **Given** 一个通过 HTTP 连接的 MCP server 暴露的工具，**When** 运行时执行工具发现与注册，
   **Then** 调用方无法从工具的调用接口区分该工具来自 stdio 还是 HTTP 传输的 server。

---

### User Story 3 - 连接与调用失败时的可靠隔离 (Priority: P3)

作为运行时的运维/接入方，当某个 MCP server 无法启动、握手超时、或在工具调用过程中失联时，
我希望获得清晰、可分类的错误信息，并且这一次失败不会影响其他已注册工具（无论是本地工具、
沙箱工具，还是来自其他 MCP server 的工具）的正常使用。

**Why this priority**: 这是生产可用性的底线要求，但依赖 P1/P2 已经建立的连接与调用路径才能
针对性设计失败分支，因此排在两者之后实现。

**Independent Test**: 可通过模拟一个无法启动的命令、一个握手无响应的进程、一个调用中途关闭
连接的进程，分别验证三类失败均被识别为对应的错误类型，且不影响同一运行时中其他工具的调用。

**Acceptance Scenarios**:

1. **Given** 一个配置的 MCP server 命令/地址实际不可达，**When** 运行时尝试连接，**Then**
   返回明确的「连接失败」错误，且不会使整个工具注册表进入不可用状态。
2. **Given** 一个已连接但随后失联的 MCP server，**When** 调用方对其已注册工具发起调用，
   **Then** 返回明确的「调用失败/连接已断开」错误，其他工具的调用不受影响。
3. **Given** 一次工具调用耗时超过配置的等待上限，**When** 等待超时，**Then** 调用方收到
   明确的超时错误，而不是无限期等待。

---

### Edge Cases

- 两个不同的 MCP server（或一个 MCP server 与一个已注册的本地/沙箱工具）暴露了同名工具时，
  系统如何处理？
- 一个 MCP server 在握手成功、工具发现完成之后，才在某次调用时才失联，如何与握手阶段失败
  区分？
- 一个 MCP server 声明的工具列表为空，是否视为一次成功的（但无新增工具的）接入？
- 主动断开一个已连接的 MCP server 后，其已注册工具是否应立即变得不可调用？
- 同一个 MCP server 是否允许被重复调用连接（幂等）而不是报错？

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 支持通过 stdio 传输（本地子进程）配置并连接一个 MCP server。
- **FR-002**: 系统 MUST 支持通过 HTTP 传输连接一个远程 MCP server，且对上层调用方提供与
  stdio 传输等价的使用体验（发现、调用接口一致）。
- **FR-003**: 系统 MUST 在使用某个 MCP server 提供的任何工具之前，完成与该 server 的初始化
  握手，确认连接可用。
- **FR-004**: 系统 MUST 在握手成功后，通过 MCP 工具发现能力获取该 server 暴露的全部工具
  及其名称、描述、输入参数结构。
- **FR-005**: 系统 MUST 将每个发现的 MCP 工具适配为运行时已有的 Tool 接口（与 005 中本地
  工具、沙箱工具共用同一接口），使其可被同一个工具注册表管理、被 ReAct 引擎按统一方式调用。
- **FR-006**: 当发现的工具名称与工具注册表中已存在的工具名称冲突时，系统 MUST 拒绝注册该
  冲突工具，并报告冲突（复用已有工具注册表的重名拒绝行为，不覆盖已注册工具）。
- **FR-007**: 系统 MUST 对每一次外部 MCP 调用（握手、工具发现、工具调用）设置明确的最大
  等待时间；任何一次调用都不得无限期等待。
- **FR-008**: 系统 MUST 将「连接/握手失败」「调用超时」「调用中途连接断开」「工具执行本身
  返回的业务失败」区分为可辨识的不同错误类别，供调用方按需处理。
- **FR-009**: 系统 MUST 保证单个 MCP server 的连接失败或调用失败不影响其他已注册工具
  （本地工具、沙箱工具、其他 MCP server 提供的工具）的正常调用。
- **FR-010**: 系统 MUST 为每一次 MCP 连接生命周期事件（连接、断开、连接失败）与每一次工具
  调用生成可观测记录，并携带发起方所属的租户标识。
- **FR-011**: 系统 MUST 支持主动断开一个已连接的 MCP server；断开后，其注册的工具不得再被
  成功调用。

### Key Entities *(include if feature involves data)*

- **MCP Server 连接配置**：描述如何连接一个 MCP server，包括传输方式（stdio 子进程命令 /
  HTTP 地址）与连接相关的等待时间上限。
- **MCP Server 连接**：一次具体的连接实例，具有连接状态（未连接/已连接/已断开/连接失败）。
- **已发现工具**：从某个已连接 MCP server 发现的单个工具，包含名称、描述、输入参数结构，
  以及其所属的连接来源。
- **工具调用结果**：一次工具调用后，MCP server 返回的结果被转换为调用方（Tool 接口调用者）
  可直接使用的字符串结果。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 接入一个新的 MCP server 后，其暴露的工具无需编写任何针对该 server 的专用适配
  代码即可被 ReAct 引擎成功调用。
- **SC-002**: 对一个提供 20 个以内工具的正常响应 MCP server，从发起连接到全部工具可被调用，
  在正常网络/进程条件下于数秒内完成。
- **SC-003**: 100% 的外部 MCP 调用（握手、工具发现、工具调用）都被一个配置的等待上限约束；
  不存在无限期挂起的调用路径。
- **SC-004**: 当一个 MCP server 不可达或失联时，运行时中其余已注册工具（本地、沙箱、其他
  MCP server）的调用成功率不受影响。

## Assumptions

- 目标 MCP 协议版本以当前稳定的 Model Context Protocol 规范为准，传输方式覆盖 stdio 与基于
  HTTP 的传输；本 feature 不追加规范之外的自定义传输协议。
- v1 范围内，MCP server 连接的重连策略为「失败后需调用方显式重新发起连接」，不在运行时内部
  实现自动重连/退避重试；这可作为后续 feature 按需增强。
- HTTP 传输的鉴权（如 Bearer token）作为每个连接配置的可选项支持，具体鉴权协议扩展超出本
  feature 范围。
- 工具调用参数与返回结果的结构由 MCP server 自身的工具 schema 定义；本 feature 只负责透传
  与格式适配为字符串结果，不对参数/结果做业务语义校验。
- 本 feature 只覆盖工具能力（tools/list、工具调用）的接入；MCP 规范中的 resources、prompts
  等其他能力不在本次范围内。
