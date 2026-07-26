# Data Model: memory 压缩与上下文管理

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

## SQLite 表结构（`storage.py` 内建表，见 research.md R2）

```sql
CREATE TABLE IF NOT EXISTS messages (
    tenant_id  TEXT NOT NULL,
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, session_id, seq)
);
```

连接建立时执行 `PRAGMA journal_mode=WAL`（research.md R2）。

## ContextBudget（配置，frozen dataclass，见 research.md R4）

| 字段 | 类型 | 默认值 | 约束 |
|------|------|--------|------|
| max_context_tokens | int | 4000 | > 0（不允许"不压缩"为默认行为） |
| keep_recent_messages | int | 6 | > 0 |

## 内部状态（不对外暴露）

- **CompactionCandidate**: 一次压缩判定的中间结果——`to_compact: list[StoredMessage]`
  （待压缩的较早消息）、`to_keep: list[StoredMessage]`（保留窗口内的消息）。
  若 `to_compact` 为空，跳过压缩（Edge Case，research.md R5）。
- **StoredMessage**: 存储层内部表示，比公共 `Message`（001 已定义）多一个
  `seq` 字段，用于事务内的删除/插入定位；对外通过 `Memory.load()` 返回时
  转换为公共 `Message` 列表（`tuple[Message, ...]`，去掉 `seq`）。

## Memory 公共接口（复用 001 冻结签名）

```python
async def load(self, session_id: str, *, tenant_id: str) -> list[Message]: ...
async def append(self, session_id: str, message: Message, *, tenant_id: str) -> None: ...
```

`SqliteMemory.__init__(self, *, db_path: str, provider: LLMProvider, model: str,
budget: ContextBudget = ContextBudget())`——`provider`/`model` 用于压缩时
发起 LLM 调用（依赖注入，延续 001/002 模式）。

## 状态流转（一次 append 调用，load 同理见下方差异说明）

```text
append(session_id, message, tenant_id)
  → 事务: SELECT MAX(seq) → INSERT 新消息（seq = max+1）（research.md R3，串行化写入）
  → 读取该 (tenant_id, session_id) 的全部消息
  → 估算总 token（字符数/4 粗估，同 001 R9）
  → 若总 token <= budget.max_context_tokens:
        结束，不触发压缩
  → 若总 token > budget.max_context_tokens:
        划分 to_compact / to_keep（保留最近 keep_recent_messages 条）
        若 to_compact 为空 → 结束，不触发压缩（Edge Case，尽力压缩）
        否则:
          调用 provider.complete(...) 生成摘要
            ├─ ProviderError 子类 → 原样上抛，本次 append 失败，
            │   原始消息（含刚插入的新消息）保持不变（FR-007）
          事务: DELETE to_compact 对应的行 + INSERT 摘要行（原子替换，research.md R5）
  → 记录 memory.append span（tenant_id, session_id, compaction_triggered）
```

`load(session_id, tenant_id)` 的差异：省略"插入新消息"步骤，其余步骤
（估算 → 判定 → 压缩 → 返回结果）相同；返回值是压缩（如触发）之后的
最终消息列表。

## 遥测 span 契约（`memory.{operation}`，见 research.md R7）

| 属性 | 值 |
|------|-----|
| span name | `memory.load` 或 `memory.append` |
| `tenant_id` | 调用方传入的 tenant_id |
| `session_id` | 调用方传入的 session_id |
| `memory.compaction_triggered` | bool |
| 父子关系 | 若触发压缩，压缩内部的 `chat {model}` span 为其子 span |
| span status | 正常完成 OK；因 provider 异常终止时 ERROR + 异常类型 |
