# Contract: 长期记忆公共 Python 接口

**Consumer**: 平台层调度器（未来 feature 006）、react 模块（未来可选集成——
新对话开始前查询、对话结束后提炼）
**Provider**: `kernel.memory`（`LongTermMemory` 类）

数据结构见 [data-model.md](../data-model.md)。

## 公共导出（`kernel.memory` 包级新增）

```python
from kernel.memory import (
    LongTermMemory,
    MemoryEntry,
    ExtractionResult,
)
```

## LongTermMemory

```python
class LongTermMemory:
    def __init__(
        self,
        *,
        db_path: str,
        provider: LLMProvider,
        model: str,
    ) -> None: ...

    async def extract(
        self, history: tuple[Message, ...], *, tenant_id: str
    ) -> ExtractionResult: ...

    async def query(self, *, tenant_id: str, limit: int = 10) -> list[MemoryEntry]: ...

    async def aclose(self) -> None: ...
```

## 行为契约

1. `extract()` 是唯一的写入入口，显式触发，MUST NOT 被任何其他操作
   自动调用（区别于 003 `SqliteMemory` 的自动压缩，FR-003）。
2. `extract()` 失败（provider 抛出的 `ProviderError` 子类）时长期记忆库
   保持提炼前的状态，MUST NOT 出现部分写入（FR-005）。
3. `query()` 的 `limit` 参数 MUST 为正整数，非正数在查询发起前拒绝（FR-006）。
4. `query()` 返回结果 MUST 按写入时间倒序排列，且 MUST NOT 超过 `limit`
   条；接口签名本身不携带任何排序策略假设，未来替换为语义检索时
   仅需替换内部实现，签名不变（FR-007）。
5. 同类别记忆条目的覆盖行为由存储层原子完成，调用方无需关心冲突处理
   细节（FR-008）。
6. 与 `kernel.memory.SqliteMemory`（003 交付）可共享同一 `db_path`，
   但两者的读写逻辑完全独立，互不调用。

## 兼容性承诺

- `LongTermMemory.__init__` 参数只增不删。
- `extract()`/`query()` 签名冻结后只做兼容式扩展（新增可选参数）。
- `MemoryEntry` 字段只增不删。
