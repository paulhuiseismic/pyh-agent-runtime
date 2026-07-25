<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0
Rationale: MINOR — 开发工作流新增 Git commit 粒度与 commit message 规范
（实质性扩展指导，未改动任何原则）。

Previous: (template, unversioned) → 1.0.0, initial ratification with 6 principles.

Modified principles: N/A (initial adoption; all template placeholders replaced)

Added sections:
- Core Principles (6 principles: 分层架构、最简实现优先、基础设施组装优先于自研、
  外部调用超时与成本上限、OTel GenAI 可观测性、测试与安全边界)
- 附加约束 (Additional Constraints)
- 开发工作流 (Development Workflow)
- Governance

Removed sections: none (template slots SECTION_2 / SECTION_3 materialized as
附加约束 / 开发工作流)

Templates status:
- .specify/templates/plan-template.md ✅ compatible (Constitution Check gate is
  derived dynamically from this file at plan time; no edits required)
- .specify/templates/spec-template.md ✅ compatible (no constitution-specific
  mandatory sections added)
- .specify/templates/tasks-template.md ✅ compatible (test tasks marked OPTIONAL
  in template, but Principle VI mandates unit tests for kernel modules —
  /speckit-tasks MUST include test tasks for kernel-module work regardless of
  spec-level test opt-in)

Follow-up TODOs: none
-->

# pyh-agent-runtime Constitution

本项目是一个多租户（multi-tenant）agent runtime。

## Core Principles

### I. 分层架构（Kernel 独立于平台层）

Agent 内核（provider、react、memory、tool 四个模块）MUST NOT 依赖平台层
（租户管理、API 网关、部署与运维设施等）。依赖方向只允许平台层 → 内核，
禁止反向依赖。内核 MUST 可以在不启动任何平台组件的情况下独立实例化和测试。

**理由**：内核是系统的可复用核心，与平台解耦才能保证独立测试、独立演进，
并防止多租户逻辑渗入 agent 推理逻辑。

### II. 最简实现优先

每个功能 MUST 以最简单、最直接的方式实现。MUST NOT 引入未经讨论的设计模式、
抽象层或"为未来预留"的扩展点。若认为确有必要引入某种模式或抽象，
MUST 先在 plan/spec 阶段提出并获得确认后再实现。

**理由**：过早抽象是本类项目最常见的债务来源；先写最直白的版本，
出现真实的重复或变化点后再抽象。

### III. 基础设施组装优先于自研

能用成熟基础设施解决的问题 MUST NOT 自研：模型路由 MUST 使用 LiteLLM，
可观测性 MUST 使用 OpenTelemetry + Langfuse。第三方组件 MUST 只通过网络 API
集成，MUST NOT fork 或修改其源码。引入任何第三方组件前，MUST 将其 license
记录到 `THIRD_PARTY.md`。

**理由**：自研基础设施偏离项目核心价值；仅经网络 API 集成保证组件可替换、
可独立升级；license 登记规避合规风险。

### IV. 外部调用超时与成本上限

所有外部调用（LLM 调用、HTTP 请求、数据库查询）MUST 设置显式超时，
禁止依赖库的隐式默认值。所有 LLM 调用 MUST 同时设置 token 上限与成本上限，
超限时 MUST 明确失败而非静默继续。

**理由**：多租户 runtime 中一个租户的失控调用会拖垮全局；
显式上限把故障域限制在单次调用内。

### V. OTel GenAI 可观测性

所有 LLM 调用、tool 执行、消息进出 MUST 发出符合 OpenTelemetry GenAI
语义约定（semantic conventions）的 span。每个 span MUST 携带 `tenant_id`
属性，无一例外。新增的调用路径若缺失 span 或缺失 `tenant_id`，
视为违宪，MUST 在合入前修复。

**理由**：多租户环境下没有 tenant 维度的遥测数据无法定位问题、
无法核算成本；统一遵循 GenAI 语义约定保证 Langfuse 等下游工具开箱可用。

### VI. 测试与安全边界

每个内核模块（provider、react、memory、tool）MUST 有单元测试，
新增或修改内核代码 MUST 附带对应测试。ReAct 循环 MUST 有最大步数限制，
达到上限时 MUST 终止并返回明确的失败结果，禁止无界循环。

**理由**：内核是所有租户共享的执行核心，回归代价最高；
无界的 agent 循环等同于无界的成本与延迟。

## 附加约束

- 技术栈边界：新增依赖前 MUST 确认其属于既有技术栈或已获确认（呼应原则 II、III）。
- 多租户隔离：任何跨租户共享的状态（缓存、连接池、memory 存储）MUST
  以 `tenant_id` 为隔离键，禁止租户间数据串访。
- 配置显式化：超时、token 上限、成本上限、ReAct 最大步数 MUST 是可配置项，
  且 MUST 有安全的默认值，不允许"无限制"作为默认。

## 开发工作流

- 每个 feature 走 Spec Kit 流程：spec → plan → tasks → implement。
- plan 阶段的 Constitution Check MUST 逐条对照本宪法六项原则做门禁检查；
  违反项 MUST 记录在 Complexity Tracking 表中并给出理由，无法给出理由则调整设计。
- 涉及内核模块的任务 MUST 包含单元测试任务（不受 spec 层"测试可选"的约定豁免）。
- Code review MUST 检查：外部调用超时、LLM 成本上限、span 与 `tenant_id`、
  第三方 license 登记。
- Git commit 粒度：规格阶段每个 Spec Kit 命令的产物（constitution/spec/plan/tasks）
  各提交一次；实现阶段以 tasks.md 的 Checkpoint（用户故事）为单位提交，
  提交时该范围测试 MUST 全绿。规格产物 MUST 在开始实现前提交，
  不与实现代码混在同一 commit。
- Commit message 格式：`[<feature-编号>] <描述>`（如
  `[001-kernel-provider] Implement US1`）；所有 commit MUST GPG 签名，
  提交前 MUST 经用户确认。

## Governance

- 本宪法优先于其他一切开发惯例；冲突时以本宪法为准。
- 修订流程：任何修订 MUST 以 PR 形式提出，说明动机与影响范围，
  并同步更新受影响的模板与文档后方可合入。
- 版本策略：遵循语义化版本。MAJOR = 删除或不兼容地重定义原则；
  MINOR = 新增原则或实质性扩展指导；PATCH = 措辞澄清与非语义修订。
- 合规审查：每次 plan 的 Constitution Check 与每次 code review
  是合规检查的两个固定关口；发现违宪且无 Complexity Tracking
  记录的实现 MUST 退回修改。

**Version**: 1.1.0 | **Ratified**: 2026-07-25 | **Last Amended**: 2026-07-25
