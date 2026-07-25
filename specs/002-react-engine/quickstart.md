# Quickstart: ReAct 引擎验证指南

**目标**: 15 分钟内本地跑通全部验证（SC-005），全程无需真实模型密钥。

## 前置条件

沿用 001 的虚拟环境（`pip install -e ".[dev]"` 已包含全部依赖，无新增）。

## 1. 单元测试（验证 SC-001 / SC-002 / SC-003）

```bash
pytest tests/unit/react -v
```

**预期**: 全部通过；过程无外部网络访问、无平台层组件、无真实模型。

## 2. stub 演示脚本（验证 US1/US2/US3）

运行示例脚本（实现阶段交付于 `examples/demo_react_stub.py`）：

```bash
python examples/demo_react_stub.py
```

**预期输出依次包含**:

1. 一次"直接回答"运行：思考一步即给出最终答案，无工具调用；
2. 一次"调用工具后回答"运行：第一步决定调用工具，工具返回观察，
   第二步据此给出最终答案；
3. 一次"步数耗尽"运行（`max_steps=2`，stub provider 永远决定调用工具）：
   捕获 `StepBudgetExceededError`，打印已执行步数与最后观察；
4. 每次运行的 console span 输出，可见 `react.step` span（含 step index /
   action / tool_name）与其下挂载的 `chat {model}` 子 span。

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 单测全绿、零平台/网络依赖 | 1 | SC-001 |
| 步数耗尽类型化终止、不超步 | 2-③ | SC-002, US2 |
| 工具失败转观察不崩溃 | 2-② | SC-003, US1 |
| span 可还原步数/工具决策 | 2-④ | SC-004, US3 |
| 15 分钟内完成 1+2 | 计时 | SC-005 |
