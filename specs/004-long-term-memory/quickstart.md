# Quickstart: 长期记忆验证指南

**目标**: 15 分钟内本地跑通全部验证，全程无需真实模型密钥。

## 前置条件

沿用 001/002/003 的虚拟环境，无新增依赖。

## 1. 单元测试

```bash
pytest tests/unit/memory -k "long_term or extraction" -v
```

**预期**: 全部通过；存储层用真实临时 SQLite 文件、提炼逻辑用 stub provider，
过程无外部网络访问、无平台层组件。

## 2. stub 演示脚本

运行示例脚本（实现阶段交付于 `examples/demo_long_term_memory_stub.py`）：

```bash
python examples/demo_long_term_memory_stub.py
```

**预期输出依次包含**:

1. 从一段包含"偏好简洁回答"的对话历史提炼出一条记忆条目并写入；
2. 查询该租户记忆，看到刚写入的条目；
3. 再次提炼一段"偏好详细回答"的对话历史（同类别）→ 查询结果显示旧条目
   已被新条目覆盖，总数未增加；
4. 用另一个 tenant_id 查询，验证看不到第一个租户的记忆；
5. 每次 extract/query 的 console span 输出，含 `tenant_id`/`operation`，
   extract 触发的 span 下挂载 `chat {model}` 子 span。

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 单测全绿、真实持久化可验证 | 1 | SC-001 |
| 跨租户隔离 | 2-④ | SC-002, US2 |
| 同类别覆盖、不无限增长 | 2-③ | SC-003, US3 |
| span 可识别 tenant_id/操作类型 | 2-⑤ | SC-004 |
| 提炼失败不写脏数据 | 单测覆盖（无需 demo 步骤） | SC-005 |
| 15 分钟内完成 1+2 | 计时 | quickstart 目标 |
