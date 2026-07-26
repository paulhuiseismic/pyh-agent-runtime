# Data Model: 长期记忆

**Date**: 2026-07-26 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

## SQLite 表结构（`long_term_storage.py` 内建表，见 research.md R3）

```sql
CREATE TABLE IF NOT EXISTS memory_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  TEXT NOT NULL,
    category   TEXT,               -- NULL 表示"无法判定类别"
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, category)   -- SQLite 对 NULL 的唯一约束语义：
                                    -- 每个 NULL 都视为不同，天然实现
                                    -- "同类别覆盖、无法判定类别独立新增"
);
```

与 003 的 `messages` 表共享同一数据库文件（同一 `db_path`），但完全独立的表，
无外键、无联合查询（FR-012：不与会话消息存储/压缩逻辑耦合）。

## MemoryEntry（对外返回结构，frozen dataclass，见 `long_term_models.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| content | str | 记忆内容文本 |
| category | str \| None | 类别标注，`None` 表示无法判定 |

## ExtractionResult（内部中间结构，提炼解析后的产物）

| 字段 | 类型 | 说明 |
|------|------|------|
| entries | list[MemoryEntry] | 本次提炼产生的记忆条目，可能为空列表 |

规则：LLM 响应无法解析为合法数组、或元素缺少 `content` 字段 → 视为
`entries=[]`（research.md R2），记一条 warning 日志，不抛异常。`category`
字段若为空字符串 `""` 或全空白，一律归一化为 `None`（视同"无法判定类别"），
避免空字符串作为一个"真实类别值"参与 `UNIQUE(tenant_id, category)` 约束——
否则多次"无法判定"的提炼会被误判为同一类别而相互覆盖。

## LongTermMemory 公共接口

```python
async def extract(self, history: tuple[Message, ...], *, tenant_id: str) -> ExtractionResult: ...
async def query(self, *, tenant_id: str, limit: int = 10) -> list[MemoryEntry]: ...
```

`LongTermMemory.__init__(self, *, db_path: str, provider: LLMProvider, model: str)`——
`db_path` 可与 003 `SqliteMemory` 使用同一路径（不同表，互不冲突）。

## 状态流转

### extract(history, tenant_id)

```text
extract(history, tenant_id)
  → 若 history 为空 → 直接返回 ExtractionResult(entries=[])，不发起 LLM 调用
  → 构造提炼请求（system 提示要求 JSON 数组输出，见 research.md R1）
  → 调用 provider.complete(...)
      ├─ ProviderError 子类 → 原样上抛，长期记忆库不受影响（FR-005）
  → 解析响应为 ExtractionResult
      ├─ 解析失败/元素缺 content → entries=[]（research.md R2）
  → 若 entries 非空：对每条记忆执行
        INSERT INTO memory_entries (tenant_id, category, content, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(tenant_id, category) DO UPDATE SET
          content = excluded.content, updated_at = excluded.updated_at
      （同类别覆盖、NULL 类别独立新增均由此一条语句原子完成，research.md R3）
  → 记录 long_term_memory.extract span（tenant_id）
  → 返回 ExtractionResult
```

### query(tenant_id, limit)

```text
query(tenant_id, limit)
  → 校验 limit 为正整数 ──否→ InvalidRequestError（复用 001 异常，查询前拒绝）
  → SELECT content, category FROM memory_entries
    WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?
  → 记录 long_term_memory.query span（tenant_id）
  → 返回 list[MemoryEntry]
```

## 遥测 span 契约（`long_term_memory.{operation}`，见 research.md R5）

| 属性 | 值 |
|------|-----|
| span name | `long_term_memory.extract` 或 `long_term_memory.query` |
| `tenant_id` | 调用方传入的 tenant_id |
| `operation` | `extract` 或 `query` |
| 父子关系 | `extract` 内部的 `chat {model}` span 为其子 span；`query` 无子 span |
| span status | 正常完成 OK；因 provider 异常终止时 ERROR + 异常类型 |
