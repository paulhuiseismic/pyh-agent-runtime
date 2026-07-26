# Research: 长期记忆

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md)

## R1. 提炼输出格式

- **Decision**: 复用 002 研究出的"结构化 JSON 输出"模式——system 提示要求
  LLM 返回 JSON 数组：`[{"category": "<字符串或 null>", "content": "<记忆内容>"}, ...]`，
  无值得记住的内容时返回空数组 `[]`。
- **Rationale**: 002 已验证结构化 JSON 比自由文本解析更可靠；数组形态天然
  支持"一次提炼产生零或多条记忆"（FR-004）。`category` 允许为 `null`
  表达"无法判定类别"（FR-008 的独立新增分支）。
- **Alternatives considered**: 自由文本 + 正则提取（脆弱，且无法可靠区分
  "类别"字段与"内容"字段）。

## R2. 解析失败的处理

- **Decision**: 若 LLM 响应不是合法 JSON 数组，或数组元素缺少 `content`
  字段，视为"本次提炼未产生可用记忆条目"（等同于空数组），记录一条 warning
  日志，不抛异常、不写入任何记忆条目。
- **Rationale**: spec 只要求"provider 调用失败"（网络/超限等）时中止并保持
  库不受影响（FR-005）；LLM 返回内容本身格式不佳属于"这次没提炼出东西"，
  不应被当作系统错误处理，符合 FR-004 的"空结果不写入"精神，避免为一个
  非关键路径引入新的异常类型（最简原则）。
- **Alternatives considered**: 抛出类似 002 `malformed` 的专门错误类型
  （过度设计——调用方并不需要区分"LLM 说没什么好记的"和"LLM 输出格式不佳"，
  两者的补救动作相同：什么都不做）。

## R3. 类别冲突处理的存储层实现

- **Decision**: 表结构 `memory_entries(id, tenant_id, category, content,
  updated_at)`，唯一约束 `UNIQUE(tenant_id, category)`。写入时统一执行
  `INSERT ... ON CONFLICT(tenant_id, category) DO UPDATE SET content=excluded.content,
  updated_at=excluded.updated_at`。SQLite 的唯一索引对 `NULL` 值的语义是
  "每个 NULL 都视为不同"，因此 `category=NULL`（无法判定类别）的记录永远
  不会与任何已有记录冲突，天然被当作独立新增；`category` 为具体字符串时，
  同租户同类别的第二次写入会命中唯一约束触发 `DO UPDATE`，天然实现覆盖。
- **Rationale**: 这是 FR-008"同类别覆盖、无法判定类别独立新增"的最简实现——
  零应用层分支逻辑，完全借助 SQLite 唯一索引对 NULL 的标准行为，不需要
  "先查询是否存在同类别记录再决定 UPDATE 还是 INSERT"这种手写的两步逻辑
  （也避免了两步之间的竞态）。
- **Alternatives considered**: 应用层先 SELECT 判断类别是否已存在再决定
  INSERT/UPDATE（多一次查询、且需要事务包裹避免竞态，SQLite 原生 UPSERT
  已经原子地做到这点）。

## R4. 查询排序与数量上限

- **Decision**: `query(tenant_id, limit)`——`limit` 必须为正整数（校验规则
  同 003 R4 的"不允许无限制"精神），查询语句为
  `SELECT content, category FROM memory_entries WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?`。
  默认 `limit=10`。接口签名不包含任何"相关性算分"参数，只接受
  "租户 + 数量"，为未来替换为语义检索（可能需要额外的 query embedding 参数）
  预留空间——即当前实现是"按时间排序"这一具体策略，接口本身不假设策略
  （FR-007）。
- **Rationale**: 时间倒序是"最近偏好通常最新"的合理近似，且实现成本为零
  （SQL `ORDER BY` 原生支持）；数量上限默认 10，覆盖典型场景下不会让
  system 提示过长。
- **Alternatives considered**: 立即引入 embedding 相似度检索（明确超出
  本 feature 范围，spec Assumptions 已声明留给未来 feature）。

## R5. 遥测标注方式

- **Decision**: 复用 001/002/003 已有的 tracer（同一 `kernel.provider`
  tracer name），每次 `extract`/`query` 发一个 `long_term_memory.{operation}`
  span，属性含 `tenant_id`、`operation`。`extract` 内部的 provider 调用
  产生的 `chat {model}` span 作为其子 span（与 002/003 一致的父子 span 模式）。
  `query` 不涉及 LLM 调用，无子 span。
- **Rationale**: 与 001/002/003 保持同一遥测架构，无需引入第二套 tracer
  配置面；父子 span 关系复用已验证的实现模式（span 创建 → 内部发起 provider
  调用 → 结束时统一 finally）。
- **Alternatives considered**: 无——与既有模式一致，没有值得权衡的替代方案。

## R6. 测试策略

- **Decision**: 存储层测试用真实临时 SQLite 文件（复用 003 R8 的测试基础
  设施模式）；提炼测试用脚本化 `httpx.MockTransport` stub provider
  （复用 001/002/003 已验证的 stub 机制），返回预设的 JSON 数组字符串。
- **Rationale**: 与既有三个 feature 的测试策略完全一致，零新增测试基础设施
  类型，保持整个内核测试栈的一致性。
- **Alternatives considered**: 无——遵循既定模式。
