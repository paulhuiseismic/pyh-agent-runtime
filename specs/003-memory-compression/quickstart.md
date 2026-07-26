# Quickstart: memory 压缩与上下文管理验证指南

**目标**: 15 分钟内本地跑通全部验证，全程无需真实模型密钥。

## 前置条件

沿用 001/002 的虚拟环境；新增依赖 `aiosqlite`（`pip install -e ".[dev]"` 会自动安装）。

## 1. 单元测试（验证 SC-001 / SC-002 / SC-003 / SC-005）

```bash
pytest tests/unit/memory -v
```

**预期**: 全部通过；存储层用真实临时 SQLite 文件、压缩逻辑用 stub provider，
过程无外部网络访问、无平台层组件。

## 2. stub 演示脚本（验证 US1/US2/US3）

运行示例脚本（实现阶段交付于 `examples/demo_memory_stub.py`）：

```bash
python examples/demo_memory_stub.py
```

**预期输出依次包含**:

1. 追加若干条消息后读取，历史完整；
2. 用不同 `tenant_id` 写入相同 `session_id`，验证互不可见；
3. 追加消息使累计 token 超过一个较小的演示预算，触发自动压缩：
   打印压缩前后的消息数量与摘要内容；
4. 每次操作的 console span 输出，可见 `memory.append`/`memory.load` span
   （含 `memory.compaction_triggered`），触发压缩时其下挂载 `chat {model}` 子 span。

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 单测全绿、真实持久化可验证 | 1 | SC-001, SC-005 |
| 跨租户隔离 | 2-② | SC-002, US1 |
| 超预算自动压缩、回落到预算内 | 2-③ | SC-003, US2 |
| span 可识别压缩发生 | 2-④ | SC-004, US3 |
| 15 分钟内完成 1+2 | 计时 | quickstart 目标 |
