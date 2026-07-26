# Research: memory 压缩与上下文管理

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md)

## R1. 异步 SQLite 驱动

- **Decision**: 使用 `aiosqlite`（MIT license）作为异步 SQLite 驱动。
- **Rationale**: `Memory` Protocol 是 async（001 冻结），标准库 `sqlite3` 是
  同步 API；`aiosqlite` 是 SQLite 官方生态中最成熟的异步封装（底层仍是
  `sqlite3`，在线程池中执行），避免自己用 `asyncio.to_thread` 包一层同步
  调用（等价工作量更大且更易出 bug）。
- **Alternatives considered**: 用 `asyncio.to_thread` 包裹标准库 `sqlite3`
  （零新依赖但需要自己管理连接在线程间的正确性，`aiosqlite` 已解决此问题）；
  引入更重的异步 ORM（如 SQLAlchemy async，过度设计，违反最简原则）。

## R2. 表结构与 WAL 模式

- **Decision**: 单表 `messages(tenant_id, session_id, seq, role, content,
  created_at)`，主键 `(tenant_id, session_id, seq)`；连接建立时执行
  `PRAGMA journal_mode=WAL`。`seq` 为该 `(tenant_id, session_id)` 下的
  自增序号，决定消息顺序。
- **Rationale**: 单表覆盖 FR-001/002/003 全部读写与隔离需求，无需额外的
  session 元数据表（session 的存在性由"是否有消息行"隐式表达，FR-003
  要求不存在的 session 返回空历史而非报错，天然满足）；WAL 模式提升
  并发读写性能且是 SQLite 官方推荐的并发场景配置。
- **Alternatives considered**: 每个 session 一个表（表数量随会话数增长，
  管理复杂，SQLite 无此必要）；额外维护 sessions 元数据表（当前需求下
  是不必要的抽象）。

## R3. 并发写入保护（Edge Case：相同 session_id 并发 append）

- **Decision**: 利用 SQLite 自身的写锁串行化（WAL 模式下单写者多读者），
  `seq` 通过 `SELECT MAX(seq)+1` 与 `INSERT` 包裹在同一个 SQLite 事务
  （`BEGIN IMMEDIATE`）内完成，避免竞态导致 `seq` 冲突或跳号。
- **Rationale**: SQLite 的事务隔离已经解决"同一进程内并发 append 到同一
  session 不丢消息、顺序一致"的需求，不需要在应用层引入额外的锁机制
  （呼应宪法最简原则与 spec Assumptions 的"不引入分布式锁组件"）。
- **Alternatives considered**: 应用层维护每个 session 的 `asyncio.Lock`
  字典（需要额外的生命周期管理——何时清理不再使用的锁——引入不必要的
  复杂度；SQLite 事务已经提供更可靠的保证）。

## R4. Token 预算与保留窗口的安全默认值

- **Decision**: `ContextBudget(max_context_tokens=4000, keep_recent_messages=6)`。
  估算 token 沿用 001 `pricing.estimate_input_tokens` 的"字符数/4"粗估策略
  （同样的已知偏差与理由，不引入 tokenizer 依赖）。
- **Rationale**: 4000 token 是一个适中的默认值——明显小于 001 provider 默认
  `max_total_tokens=8192`，确保压缩后的历史加上新一轮对话仍有余量；保留
  最近 6 条消息足以覆盖典型的"最近几轮问答"，避免压缩后近期上下文失真。
  两者均可配置，均为正数，符合"不允许无限制"的宪法精神。
- **Alternatives considered**: 复用 provider 的 `max_total_tokens` 作为
  预算（耦合了两个不同层次的限额语义——一个是"单次调用"上限，一个是
  "会话历史"上限，混用会在调用方同时使用不同 limits 时产生歧义）。

## R5. 压缩范围判定与摘要生成

- **Decision**: 读取历史后，若总估算 token 超过 `max_context_tokens`，
  取"除最近 `keep_recent_messages` 条外"的消息作为压缩候选；若候选集合为空
  （Edge Case：所有消息都在保留窗口内），跳过压缩（按 spec Edge Cases
  处理为"尽力压缩"，不视为错误）。候选消息拼接后，通过 provider 发起一次
  `role=user` 的总结请求（system 提示要求"用简洁的第三人称摘要保留关键
  事实"），返回内容作为一条新的 `role=system` 摘要消息，替换原候选消息
  （在同一 SQLite 事务内：删除候选行 + 插入摘要行，保证原子性——不会出现
  "删了旧消息但摘要未写入"的中间状态）。
- **Rationale**: 原子替换是 FR-007"压缩失败时原始历史不被破坏"的关键
  实现手段——先调用 provider 拿到摘要内容成功后，才在一个事务内做替换；
  若 provider 调用失败，事务从未开始，原始数据完全不受影响。
- **Alternatives considered**: 先删除再调用 provider（错误顺序，
  provider 失败会导致数据已丢失，违反 FR-007）；增量式摘要（每次只摘要
  一小批, 复杂度更高，无法带来当前需求下的额外收益）。

## R6. 压缩触发时机（append 与 load 均可触发）

- **Decision**: `append` 与 `load` 内部共用同一个"检查预算→按需压缩→
  返回/继续"的私有方法；`append` 在写入新消息后立即检查是否超预算并压缩，
  `load` 在读取历史后同样检查（覆盖"很久没有新消息但下次 load 时才发现
  超预算"的场景，例如外部直接写入大量历史数据的边缘情况）。
- **Rationale**: spec FR-004 明确要求"在 append 或 load 时检测超限并触发"，
  两处复用同一压缩方法保证行为一致，不会出现 append 触发的压缩逻辑与
  load 触发的不一致。
- **Alternatives considered**: 只在 append 时检查（更简单，但不满足 spec
  对 load 也要触发压缩的显式要求）。

## R7. 遥测标注方式

- **Decision**: 复用 001/002 已有的 tracer（`kernel.provider` tracer name，
  与 002 的 `react.step` 保持同一套 tracer 配置面），每次 `load`/`append`
  发一个 `memory.{operation}` span（`operation` 为 `load` 或 `append`），
  属性含 `tenant_id`、`session_id`、`memory.compaction_triggered`（bool）。
  若触发压缩，压缩内部的 provider 调用产生的 `chat {model}` span 作为
  该 span 的子 span（与 002 的父子 span 模式一致）。
- **Rationale**: 与 001/002 保持同一遥测架构（同一 tracer、GenAI 语义
  子 span 挂载模式），审计工具无需适配第二套 tracer 配置。
- **Alternatives considered**: 为 memory 单独建 tracer name
  （不必要的配置面增加，且父子 span 关系仍需同一 TracerProvider 才能
  正确嵌套，单独 tracer 无额外收益）。

## R8. 测试策略（真实临时文件 vs mock）

- **Decision**: 存储层测试用 `tempfile.TemporaryDirectory` 创建真实
  SQLite 文件，验证真实的持久化/重启后可读（spec US1 场景 2 要求"进程
  重启后依然可读"，mock 存储层无法验证这一点）；压缩逻辑测试复用
  001/002 的 `httpx.MockTransport` stub provider。
- **Rationale**: SQLite 文件读写是本地文件系统操作，速度足够快
  （毫秒级），用真实文件不会拖慢测试套件，同时能验证 SC-005（持久化
  数据重启后完整恢复）这一在 mock 层面无法验证的关键要求。
- **Alternatives considered**: 内存态 `:memory:` SQLite（无法验证"进程
  重启后可读"，因为内存数据库随连接关闭而消失）。
