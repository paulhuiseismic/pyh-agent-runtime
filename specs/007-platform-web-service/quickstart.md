# Quickstart: 平台服务层 + web service（REST API）验证指南

**目标**: 15 分钟内本地跑通全部验证，全程无需真实模型密钥、无需真实网络
（内核调用全部 stub 化，同 001-006 的测试哲学）。

## 前置条件

在 001-006 虚拟环境基础上安装本 feature 新增依赖：

```bash
pip install -e ".[dev]"
```

（`fastapi` 已加入 `pyproject.toml` 核心依赖；`uvicorn` 从传递依赖提升为
直接依赖）

## 1. 单元测试（验证 SC-001 / SC-002 / SC-003 / SC-004 / SC-005）

```bash
pytest tests/unit/platform_service -v
```

**预期**: 全部通过，涵盖配置校验、鉴权成功/失败、并发调度（单租户超限、
全局超限、租户间隔离）、`AgentService` 端到端组合调用（含会话记忆读写）、
FastAPI 六类响应（成功/鉴权失败/并发超限/参数校验失败/内核失败/超时）。

## 2. 启动真实进程验证（可选，验证 SC-006 的"薄适配"设计）

```bash
python -m uvicorn platform_service.app:app --port 8000
```

另开终端：

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/run \
  -H "X-API-Key: demo-key" \
  -H "Content-Type: application/json" \
  -d '{"goal": "1+1 等于几？"}'
```

（示例配置 `examples/platform_config.example.json` 中 `demo-key` 对应的
租户使用 stub provider，返回固定答案，无需真实模型密钥）

**预期输出**: `{"status": "success", "answer": "...", "session_id": null}`

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 调用方无需了解内核内部组合即可获得结果 | 1（`test_app.py` 成功场景）、2 | SC-001 |
| 未携带合法租户标识 100% 被拒绝 | 1（`test_auth.py`/`test_app.py` 401 场景） | SC-002 |
| 并发上限触达时明确拒绝、非无限期挂起 | 1（`test_scheduler.py`/`test_app.py` 429 场景） | SC-003 |
| 一个租户超限不影响其他租户 | 1（`test_scheduler.py` 隔离场景） | SC-004 |
| 内核 span 100% 携带一致 tenant_id | 1（`test_agent_service.py` span 断言） | SC-005 |
| REST 与未来 CLI 复用同一 `AgentService` | contracts/agent-run-api.md 契约本身 + `test_agent_service.py` 不经过 HTTP 直接调用 | SC-006 |
| 15 分钟内完成 1+2 | 计时 | 效率基线（同 001-006 惯例） |
