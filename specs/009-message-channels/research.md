# Research: message 多渠道收发（消息网关）

## R1: 异步处理机制——`asyncio.create_task` vs 任务队列

**Decision**: 用标准库 `asyncio.create_task()` 在接入端点内调度后台
处理，不引入任何消息队列/任务调度第三方库（如 Celery、RQ、Dramatiq）。

**Rationale**: spec.md 的 Assumptions 已明确"不引入消息队列/持久化重试
基础设施"，v1 是单进程部署，`asyncio.create_task` 足以满足"接入立即
确认、处理在后台异步完成"的核心诉求；引入任务队列会带来额外的部署
依赖（broker、worker 进程）与运维复杂度，不符合宪法原则 II 的最简
实现优先。进程崩溃导致尚未完成的后台任务丢失是明确接受的 v1 权衡
（spec.md Assumptions）。

**Alternatives considered**:
- 引入 Celery/RQ 等任务队列——提供持久化重试与跨进程扩展能力，但需要
  额外的 broker（Redis/RabbitMQ）与独立 worker 进程，超出 v1 范围，
  且未经用户确认引入新的技术栈组件（宪法原则 III 的"新增依赖前需确认"），
  拒绝。
- 用 FastAPI/Starlette 内置的 `BackgroundTasks`——表面上更"框架原生"，
  但 Starlette 会在 ASGI 应用返回响应前等待 `BackgroundTasks` 执行
  完成（响应体已发送给客户端，但 ASGI 应用可调用对象本身未返回），
  这会导致 `httpx.ASGITransport`（内存直调，无真实 socket）测试中
  客户端调用的等待时间实际上仍然包含了后台处理耗时，无法真实验证
  SC-001"接入确认不受处理耗时影响"这一行为契约。改用独立的
  `asyncio.create_task()`（不由请求处理协程 await）能让接入端点的
  返回真正独立于后台任务的完成时机，测试与生产行为一致，故拒绝
  `BackgroundTasks`。

## R2: 测试如何确定性等待后台任务完成

**Decision**: `MessageGateway` 持有 `self._background_tasks: set[asyncio.Task]`
（防止任务被垃圾回收，遵循 asyncio 官方推荐做法），并暴露
`async def wait_for_background_tasks(self) -> None`（`await
asyncio.gather(*self._background_tasks)`，测试专用）。测试在断言出站
回调是否被调用前先调用该方法，而不是用 `asyncio.sleep()` 猜测耗时或
轮询。

**Rationale**: 真实 sleep/轮询会让测试变慢且存在时序不确定性（CI 环境
下偶发失败风险）；暴露一个显式的"等待所有已调度任务完成"方法是这类
fire-and-forget 异步设计的常见可测试性模式，成本低（几行代码），
换来测试的确定性与速度。

**Alternatives considered**:
- 让测试直接持有并 await 任务返回的 `asyncio.Task` 对象——需要
  `handle_inbound()` 把 Task 对象暴露给调用方，但生产路径（真实 HTTP
  请求）没有自然的"调用方"可以持有这个 Task，会导致生产签名为了
  测试而复杂化，拒绝；改为在网关内部集中持有并提供统一的等待入口。

## R3: 出站回调重试策略

**Decision**: `send_callback_with_retry()` 采用"固定次数（
`callback_max_retries`，默认 3）+ 固定短间隔（代码内常量，不作为
用户可配置项）"的重试策略，每次尝试都受 `callback_timeout_seconds`
显式超时约束；全部尝试失败后只记录警告日志，不向调用方（后台任务
本身）抛出异常——回调投递失败是外部系统的问题，不应影响本进程的
稳定性。

**Rationale**: 满足宪法原则 IV"外部调用显式超时 + 有限重试"的核心
要求即可，固定间隔足够简单直接（宪法原则 II）；把重试间隔做成用户
可配置项是对一个次要调优细节的过度设计，故不作为 `PlatformConfig`
字段暴露，只暴露真正影响外部可观察行为边界的两项
（`callback_timeout_seconds`/`callback_max_retries`）。

**Alternatives considered**:
- 指数退避——更"生产级"，但增加实现与测试复杂度（需要控制测试运行
  耗时不因退避而变长），v1 的固定间隔已能验证"有限重试"这一行为契约，
  拒绝。
- 重试次数用户不可配置（硬编码）——但 FR-008 明确要求"有限次数"是
  一个可观察、可验证的行为契约，把它做成显式配置项更符合宪法附加
  约束"配置显式化"的精神，且与 007 `global_max_concurrent_requests`
  等既有可配置上限项风格一致，故保留为配置项。

## R4: 重复投递去重存储

**Decision**: `ProcessedMessageRegistry` 用一个 `asyncio.Lock` 保护的
`set[tuple[str, str]]`（键为 `(channel_id, external_message_id)`），
提供原子的 `check_and_mark()` 方法（检查是否存在、不存在则立即标记，
一次锁内完成，避免竞态）。

**Rationale**: 与 007 `ConcurrencyScheduler.try_acquire()`（检查+自增
在同一把锁内完成）同样的原子性写法；v1 单进程部署下，进程内存 `set`
足以满足"同一进程生命周期内识别重复投递"的核心诉求（spec.md
Assumptions 已明确不追求跨进程强一致性）。

**Alternatives considered**:
- 引入 Redis/数据库持久化去重表——具备跨进程/重启后仍能去重的能力，
  但引入新的外部依赖或数据库表，超出 v1 范围，留给未来按需评估
  （呼应 spec.md 的"不追求跨进程强一致性"假设）。

## R5: 消息处理超时复用现有配置项

**Decision**: 后台处理 `AgentService.handle()` 复用既有的
`PlatformConfig.request_timeout_seconds`（007 已引入），不新增重复的
"消息处理超时"配置项。

**Rationale**: 007/008/009 三个入口本质上都是"一次调用 `AgentService`
的最长等待时间"这同一个概念，没有理由为消息网关单独定义一个语义相同
的新字段——这会造成配置项冗余、未来容易出现"改了一个忘了改另一个"
的不一致风险，违反最简实现优先原则。

**Alternatives considered**:
- 新增独立的 `message_processing_timeout_seconds`——为消息网关单独
  调优处理超时预留灵活性，但当前没有任何已知场景需要消息网关的处理
  超时与 REST/CLI 不同，属于"为假设的未来差异化需求预留"的过度设计
  （呼应宪法原则 II），拒绝。
