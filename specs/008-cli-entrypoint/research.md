# Research: CLI 入口（复用平台服务层）

## R1: 环境变量命名

**Decision**: 复用 007 已有的 `PLATFORM_SERVICE_CONFIG`（配置文件路径）；
新增 `PLATFORM_SERVICE_API_KEY`（租户 API Key），与前者共享 `PLATFORM_SERVICE_`
前缀。`--config` 命令行参数可覆盖环境变量（显式传参优先），API Key
则只允许通过环境变量传入，不提供对应的命令行参数（spec.md FR-002）。

**Rationale**: 与 007 已确立的命名风格一致，降低运维记忆负担
（同一进程组的两个入口共享前缀）；API Key 不做命令行参数是 spec.md
明确约束（避免 shell 历史/`ps`/进程列表泄露租户凭据）。

**Alternatives considered**:
- 为 CLI 单独设计一套新的环境变量前缀——增加认知负担，且与 007 已建立的
  约定无正当理由不一致，拒绝。
- API Key 支持命令行参数作为环境变量的 fallback——违反 spec.md FR-002
  的用户已确认约束，拒绝。

## R2: 退出码方案

**Decision**: 定义 7 个互斥的退出码常量（0 表示成功，1-6 分别对应
FR-006 列出的六类失败：缺少 API Key、身份识别失败、配置无效、参数校验
失败、内核处理失败、请求超时），在 `cli.py` 模块顶层以具名常量导出并在
`contracts/cli-contract.md` 中固定其数值，视为对外契约的一部分（脚本
可依赖具体数值做分支判断）。（`/speckit-analyze` F1 修正后不再包含
并发上限超出——见 R3。）

**Rationale**: spec.md SC-006 要求"使用者查看退出码即可 100% 区分"六类
失败，具名常量 + 契约文档固定数值，避免未来重构时无意间打乱数值含义。

**Alternatives considered**:
- 只用 0/1 区分成功/失败，失败原因只体现在 stderr 文本——不满足
  SC-006"无需查看内部日志即可区分"的可编程判断需求，拒绝。
- 复用 HTTP 状态码数值（如 401/429/502/504）作为退出码——超出 shell
  退出码的传统合法范围（0-255 内虽可行，但语义上容易被误认为真的是
  HTTP 状态码，误导性强），拒绝。

## R3: 单进程内是否仍需要 `ConcurrencyScheduler`

**Decision**（`/speckit-analyze` F1 修正后）：CLI 的 `run()` **不**实例化
007 的 `ConcurrencyScheduler`，直接调用 `AgentService.handle()`（跳过
调度这一环节）。

**Rationale**: 最初方案（仍实例化 `ConcurrencyScheduler` 以求"零分叉"）
在 `/speckit-analyze` 中被判定为 CRITICAL 问题（F1）：单次 CLI 命令
执行只产生一次调用，而 `max_concurrent_requests`/
`global_max_concurrent_requests` 恒为正整数，一个全新构造的调度器的
首次 `try_acquire` 在单进程单次调用场景下**必然成功**——
`EXIT_CONCURRENCY_EXCEEDED` 因此在生产环境下不可能被触发，是一段
"正常情况下必然通过、无法被真实触发"的死代码；其测试（原计划的
"预先 try_acquire 占满"）也因为调度器实例是 `run()` 内部构造、外部
无法注入而根本无法实现。唯一支撑保留它的理由是"为未来若 CLI 扩展为
长驻进程预留可能性"——这正是宪法原则 II 明确禁止的"未经讨论确认的
'为未来预留'扩展点"。故改为直接跳过，符合最简实现优先原则；
`AgentService.handle()` 本身的鉴权/超时/内核调用行为不受影响，
`AgentService`/`resolve_tenant`/`PlatformConfig` 仍然是唯一被复用、
零改动的组件（SC-003 的复用承诺范围相应收窄为不含调度器）。

**Alternatives considered**:
- 仍实例化 `ConcurrencyScheduler`，但为 `run()` 增加可选的
  `scheduler` 注入参数以便测试——能让代码"可测试"，但生产路径下
  这段逻辑依然是死代码，测试也只是在验证一个人为构造出来、脱离真实
  使用场景的状态，未解决"为假设未来场景引入未讨论抽象"的根本问题，
  拒绝。
- 跳过 `ConcurrencyScheduler`，直接调用 `AgentService.handle()`
  （最终选择）——更少代码，且不引入任何无法在 v1 单进程单次调用场景下
  被真实触发的检查路径。

## R4: 测试策略——避免真实子进程开销

**Decision**: 核心测试通过直接调用 `cli.run(argv, env, agent_service=...)`
这一异步函数完成，注入 stub `AgentService`（或注入 stub provider 后走
`build_agent_service`），断言返回的退出码与 stdout/stderr 文本，不启动
真实操作系统子进程。仅补充一个基于 `subprocess.run([sys.executable, "-m", ...])`
或已安装 console script 的最小冒烟测试，验证 `pyproject.toml` 的打包声明
本身可用（这一点无法通过直接函数调用验证）。

**Rationale**: 延续 001-007 全程"stub 化、零外部依赖、测试快"的约定；
子进程调用启动开销大且难以注入 stub provider，只用于验证打包链路这一
无法被单元测试覆盖的层面。

**Alternatives considered**:
- 全部测试都走真实子进程——更贴近用户真实使用路径，但会使测试套件
  变慢、且需要真实（或至少可达的）LLM 服务或复杂的 stub 注入机制才能
  驱动子进程内的 provider，拒绝。

## R5: CLI 归属的包结构

**Decision**: 新增的 `cli.py` 放入既有 `src/platform_service/` 包，
不新建独立顶层包（如 `src/cli/`）。

**Rationale**: architecture 文档（README.md）已明确"CLI 与 WEB 两个入口
共享同一平台服务层，仅作为薄适配器存在"；`app.py`/`cli.py` 都只是
"外部形式 ↔ `AgentService`"的薄适配层，放在同一个包内更直接体现
"平台服务层"是唯一的核心实现、入口只是形式差异这一架构意图，
也避免跨包 import 增加不必要的复杂度（呼应宪法原则 II）。

**Alternatives considered**:
- 新建 `src/cli/` 独立顶层包，import `platform_service`——增加一层包
  边界但没有带来任何独立测试/独立部署的实际价值（CLI 不会脱离
  `platform_service` 的实现单独存在），违反最简实现优先原则，拒绝。

## R6: 会话串行化（`SessionLockRegistry`）在 CLI 场景下的角色

**Decision**: 不做任何 CLI 专属处理——`SessionLockRegistry` 是
`AgentService` 内部实现细节，CLI 通过复用同一个 `AgentService` 实例
（或同一进程内构建的实例）自动获得同样的会话串行化保护；单次 CLI
命令执行本身只发起一次请求，不存在"同一进程内并发多个请求竞争同一
`session_id`"的场景，因此这一机制在 CLI 场景下始终processed为"申请锁
成功、无需等待"。

**Rationale**: 与 R3 同样的复用原则——不为 CLI 新增任何专属逻辑，
完全通过复用既有类型自然获得一致行为。

**Alternatives considered**: 无——本项无实质性替代方案需要评估，
仅作为设计澄清记录在案。
