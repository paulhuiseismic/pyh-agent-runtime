# Research: 多租户强化与审计

## R1: 如何在不修改冻结内核接口的前提下获得一次调用的用量/成本

**Decision**: 在 `AgentService._handle_locked()` 内部，为**每次调用**
构造一个轻量的委托包装类 `_UsageTrackingProvider`——它对外暴露与
`LLMProvider.complete()` 相同的异步方法签名，内部把调用转发给真实的
`self._provider`，同时把每次 `LLMResponse.usage`/`cost_usd` 累加到
一个仅存活于本次 `handle()` 调用期间的本地计数器。把这个包装器（而非
共享的 `self._provider`）传给本次调用新建的 `ReactEngine`
（`ReactEngine` 本身就是每次调用新建一个实例，见 007
`agent_service.py` 既有实现），`ReactEngine`/`LLMProvider` 全程无感知，
`engine.run()` 返回或抛出后即可从包装器读取本次调用的总用量/成本。

**Rationale**: `ReactEngine.run()`（002，已冻结）只返回最终答案文本，
中间每一步的 `LLMResponse`（含 usage/cost）在 `_run_one_step()` 内被
使用后即丢弃，不向上传播；`LLMProvider.complete()`（001，已冻结）
同样不提供任何"累计用量"的旁路读取接口。委托包装器方案完全不触碰
这两个冻结签名，且天然是"每次调用一个全新实例"（与 `ReactEngine` 的
既有生命周期完全对齐），不存在跨请求状态污染的并发风险。

**Alternatives considered**:
- 用一个自定义 `SpanProcessor` 挂到全局 `TracerProvider` 上，在
  `chat {model}` 子 span 结束时按 `trace_id` 累加用量，在
  `platform.request` 根 span 结束时读取汇总并写入审计——概念上更
  "组装优先"（复用已有 OTel 遥测数据），但存在两个实际工程问题：
  (a) OTel Python SDK 没有公开、稳定的"移除单个 SpanProcessor"API，
  在长期运行的测试进程（同一 pytest session 内几十个测试反复构造/
  销毁临时 SQLite 文件）中会导致处理器无限累积在全局
  `TracerProvider` 上，后续测试的 span 触发早已失效（指向已删除临时
  文件）的旧处理器，引发难以排查的偶发失败；(b) 生产环境下这一方案
  同样让"审计存储的生命周期"隐式绑定到"全局遥测管线的生命周期"，
  两者本应是独立可替换的关注点。故拒绝，改用更简单、生命周期显式、
  无跨请求全局状态的委托包装器方案。
- 修改 `ReactEngine.run()`，让它额外返回一个用量汇总对象——直接、
  但改动了 002 已冻结的公共返回类型，且需要同步修改
  002 自身的单元测试与规格文档，超出本 feature"零改动内核"的既定
  原则，拒绝。
- 修改 `LLMProvider`，增加一个"当前累计用量"的实例级计数器供外部
  读取——`LLMProvider` 实例是跨请求共享的单例（`build_agent_service`
  只构造一次），实例级计数器会在并发请求间相互污染，且同样需要改动
  001 已冻结代码，拒绝。

## R2: `AgentService` 的向后兼容扩展方式

**Decision**: `AgentService.__init__` 新增 `audit_store: AuditStore |
None = None`；`handle()` 新增 `source: str = "unknown"`。两者均为
带默认值的新增关键字参数，007-009 所有现存直接构造
`AgentService(...)`/调用 `handle(...)` 的测试与 demo 脚本零改动即可
继续通过（`audit_store=None` 时审计与配额检查均静默跳过，等价于
"未启用本 feature"）。

**Rationale**: 007 contracts/agent-run-api.md 的兼容性承诺明确允许
"`AgentService.handle()` 的方法签名冻结后只做兼容式扩展"——新增带
安全默认值的可选参数属于此类扩展，不破坏任何既有调用方。避免了
为了这一个 feature 去批量修改 007/008/009 已经写好并通过的数十个
测试文件的构造调用（不必要的改动面扩大，违反最简实现优先）。

**Alternatives considered**:
- 把 `audit_store` 做成必填参数——强制所有调用方显式决定是否启用
  审计，语义上更"诚实"，但会立即破坏 007-009 现有全部
  `AgentService(...)` 直接构造调用点（测试、demo），改动面过大，
  拒绝。

## R3: 查询端点是否需要 `ConcurrencyScheduler`/超时包裹

**Decision**: `GET /v1/audit/usage` 不接入 `ConcurrencyScheduler`，
不用 `asyncio.wait_for` 包裹。

**Rationale**: 该端点只做一次本地 SQLite 聚合查询，不调用
`AgentService`/`LLMProvider`/任何外部网络服务；`ConcurrencyScheduler`
保护的是"LLM 调用这类昂贵、可能阻塞的外部资源"，与一次本地文件读取
的资源特征完全不同，套用会是无意义的额外复杂度（呼应最简实现优先）。
`aiosqlite` 查询本身仍是异步 I/O，不会阻塞事件循环。

**Alternatives considered**:
- 统一套用与 `/v1/agent/run` 相同的调度/超时模式，追求"所有端点
  行为一致"的表面一致性——但会引入没有实际保护意义的空转逻辑，
  拒绝。

## R4: 配额窗口与查询时间范围的默认语义

**Decision**: 配额窗口固定为"当前 UTC 自然日"（`datetime.now(UTC)`
取整到当日 0 点作为窗口起点）；查询端点的 `start`/`end` 参数可选，
缺省时 `start` = 当日 UTC 零点、`end` = 当前时间——与配额窗口使用
同一个"今天"语义，方便运维快速核对"配额检查看到的数字"与"我自己
查到的数字"是否一致（呼应 FR-008/SC-007 的口径一致性要求）。

**Rationale**: spec.md Assumptions 已明确 v1 不支持自定义窗口长度；
查询端点的默认范围与配额窗口保持同一语义，用户无需额外心智负担
去分辨"配额算的是哪段时间"和"我查询默认看到的是哪段时间"。

**Alternatives considered**:
- 查询端点默认返回"最近 24 小时滚动窗口"而非"当日 UTC 零点起"——
  更符合"最近一天"的直觉，但与配额窗口（固定按自然日）语义不一致，
  容易造成"为什么配额没超但我查到的用量看起来更高/更低"的困惑，
  拒绝，两者统一为同一种"自然日"语义。

## R5: 查询端点的越权访问防护方式

**Decision**: `GET /v1/audit/usage` 不接受调用方传入的 `tenant_id`
参数——查询的租户永远是 `resolve_tenant(x_api_key, config)` 解析出的
调用方自身租户。

**Rationale**: 这是实现 FR-005（"只允许查询自身租户数据"）最简单、
从设计上排除越权可能的方式——没有可篡改的 `tenant_id` 参数，就不
存在"传入别人的 tenant_id"这个攻击面，比"接受参数 + 事后校验是否
匹配"更简单也更安全（宪法原则 II）。

**Alternatives considered**:
- 接受 `tenant_id` 查询参数，端点内校验其是否等于
  `resolve_tenant()` 解析出的租户，不匹配则 403——功能等价，但多了
  一个本可以从设计上直接消除的校验分支与对应的失败路径测试，拒绝。

## R6: 配额检查的并发一致性（`/speckit-analyze` F1 修正）

**Decision**: 当且仅当某租户配置了 `daily_cost_quota_usd` 时，
`handle()` 用一个按 `tenant_id` 惰性创建的 `asyncio.Lock`
（`QuotaLockRegistry`，与既有 `SessionLockRegistry` 同写法）把
"配额检查 → 内核调用 → 审计记录写入"整段临界区串行化；未配置配额的
租户完全不经过此锁，行为不受影响。

**Rationale**: 初版设计（`/speckit-analyze` 前）只是一次无同步保护
的"读取累计成本→比较"，同一租户并发发起的多个请求会全部读到检查
发生前的同一个累计成本、全部判定"未超限"、全部放行——这正是 spec.md
Edge Cases 明确要求避免的"明显超额放行"，属于 CRITICAL 级别的功能
缺口（`/speckit-analyze` F1）。由于单次调用的真实成本要等
`ReactEngine.run()`（可能耗时数秒）完成后才知道，"检查"与"写入"之间
的时间窗口本身就很大，只在读取那一刻加锁并不能消除竞态，只能缩小
概率。要从根本上消除竞态，唯一足够简单且正确的办法是把"检查"到
"写入"这整段路径当作一个不可分割的临界区，对配置了配额的租户执行
"同一时刻最多一个请求在途"的串行化——这是能完全消除该竞态的最简
方案（宪法原则 II），代价是这些租户的请求不再互相并发处理，但这本身
就是"配置配额"这一选择的合理代价（要精确控制花费，就要接受这部分
请求排队处理）。未配置配额的租户零开销、零行为变化，完全符合
FR-006/SC-006。

**Alternatives considered**:
- 只在"读取累计成本"这一步加锁，不覆盖后续的内核调用与写入——
  实现更简单，但无法解决问题：多个请求仍可能都在"读取到未超限"之后
  依次进入内核，只是不再是"同时刻读到完全相同的值"，超额放行依然
  会发生，只是概率降低而非消除，不满足彻底修复的目标，拒绝。
- 引入"预扣（reserve）"机制——检查通过时先按估算成本预扣配额，
  实际成本产生后再修正——能在不牺牲并发度的前提下更精确地防止
  超额，但需要设计"如何估算未发生的成本""预扣失败/请求失败时如何
  回滚"等一整套新状态机，复杂度显著高于直接串行化，且短期内没有
  已知场景需要"配额租户仍可高并发"这一能力，超出 v1 最简范围，
  留给未来按需评估。
- 完全不修复，只在 spec.md 里把该 Edge Case 降级为"已知限制"——
  技术上省事，但配额功能存在"设计上应该防止却完全防不住"的漏洞，
  与 US3 本身的存在目的（防止租户成本失控）相悖，拒绝。
