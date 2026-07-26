# Contract: memory 公共 Python 接口

**Consumer**: 平台层调度器（未来 feature 005）、react 模块（未来可选集成）
**Provider**: `kernel.memory`

数据结构见 [data-model.md](../data-model.md)。

## 公共导出（`kernel.memory` 包级）

```python
from kernel.memory import (
    Memory,           # Protocol（001 已冻结，签名不变）
    SqliteMemory,     # 完整实现，替换 NoopMemory
    ContextBudget,
)
```

## SqliteMemory

```python
class SqliteMemory:
    def __init__(
        self,
        *,
        db_path: str,             # SQLite 文件路径（含 :memory: 仅供非持久化场景，
                                   # 生产使用需指向真实文件路径以满足 FR-001 重启可读）
        provider: LLMProvider,    # 压缩时发起 LLM 调用，来自 kernel.provider
        model: str,               # 压缩摘要调用使用的模型
        budget: ContextBudget = ContextBudget(),
    ) -> None: ...

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]: ...
    async def append(self, session_id: str, message: Message, *, tenant_id: str) -> None: ...
    async def aclose(self) -> None: ...  # 释放底层 SQLite 连接
```

## 行为契约

1. `load`/`append` 满足 001 冻结的 `Memory` Protocol，可直接替换
   `NoopMemory` 用于任何已依赖该 Protocol 的调用方。
2. 相同 `session_id` 在不同 `tenant_id` 下的数据完全隔离（FR-002/SC-002）。
3. `load` 对不存在的 `session_id` 返回空列表，不抛异常（FR-003）。
4. 压缩自动触发，调用方无需感知；压缩失败时 `kernel.provider.errors.
   ProviderError` 子类原样上抛，原始历史不受影响（FR-007）。
5. 每次操作产生 `memory.load`/`memory.append` span，压缩发生时可从
   `memory.compaction_triggered` 属性识别（FR-008）。
6. 不修改 001 已冻结的 `kernel.provider` 与 `kernel.memory.Memory` Protocol。

## 兼容性承诺

- `SqliteMemory.__init__` 的参数只增不删；`load`/`append` 签名冻结于 001，
  本 feature 不得修改（FR-011）。
- `ContextBudget` 字段只增不删，新增字段须有默认值。
