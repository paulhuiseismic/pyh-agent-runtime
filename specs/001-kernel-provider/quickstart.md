# Quickstart: 内核骨架与 provider 模块验证指南

**目标**: 15 分钟内在本地跑通全部验证（对应 SC-004），全程无需真实模型密钥。

## 前置条件

- Python 3.12
- 无需网络（单元测试与 stub 演示完全本地）；仅"可选步骤 3"需要 Docker

## 1. 安装与单元测试（验证 SC-001 / SC-005）

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest tests/unit -v
```

**预期**: 全部测试通过；过程无外部网络访问、无平台层组件。

## 2. stub 演示脚本（验证 US1/US2/US3）

运行示例脚本（实现阶段交付于 `examples/demo_stub.py`），它用
`httpx.MockTransport` 模拟 proxy、`ConsoleSpanExporter` 输出遥测：

```bash
python examples/demo_stub.py
```

**预期输出依次包含**:

1. 一次成功调用：打印 `LLMResponse`（content / usage / cost_usd）；
2. 一次超时调用：捕获并打印 `CallTimeoutError`；
3. 一次成本超限调用：捕获并打印 `CostLimitExceededError(actual, limit)`；
4. 每次调用对应一条 console span，属性含 `tenant_id`、`gen_ai.request.model`、
   token 用量；失败调用的 span status 为 ERROR。

抽查任一 span 可读出租户/模型/用量/成本 → 验证 SC-002。

## 3. （可选）对接真实 LiteLLM proxy

需要 Docker 和至少一个模型 key（或本地 Ollama）：

```bash
# litellm-config.yaml 最小示例见 contracts/litellm-proxy-contract.md
docker run -p 4000:4000 -v ./litellm-config.yaml:/app/config.yaml \
  ghcr.io/berriai/litellm:main-stable --config /app/config.yaml

python examples/demo_proxy.py   # base_url=http://localhost:4000
```

**预期**: 与 stub 演示相同的行为契约（此步验证契约与真实 proxy 的一致性，
不属于单元测试范围）。

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 单测全绿、零平台/网络依赖 | 1 | SC-001, SC-005, US4 |
| 成功调用返回统一响应 | 2-①| US1 |
| 三类超限明确失败 | 2-②③ | US2, SC-003 |
| span 必带 tenant_id、失败也有 span | 2-④ | US3, SC-002 |
| 15 分钟内完成 1+2 | 计时 | SC-004 |
