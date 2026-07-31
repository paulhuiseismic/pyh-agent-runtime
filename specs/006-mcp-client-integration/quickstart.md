# Quickstart: MCP 客户端接入验证指南

**目标**: 15 分钟内本地跑通全部验证，全程无需外部网络、无需真实第三方 MCP
server 部署（stdio/HTTP 两种传输的测试对端均在测试进程内以官方 SDK
`FastMCP` 自建）。

## 前置条件

在 001-005 虚拟环境基础上安装本 feature 新增依赖：

```bash
pip install -e ".[dev]"
```

（`mcp` 包已加入 `pyproject.toml` 的核心依赖，随 `pip install -e .` 一并安装）

## 1. 单元测试（验证 SC-001 / SC-003 / SC-004）

```bash
pytest tests/unit/tool -v -k mcp
```

**预期**: 全部通过，涵盖 stdio 连接发现调用、HTTP 传输等价性、重名注册
冲突、连接失败/超时/中途断连三类失败隔离、遥测 span 属性与容错。

## 2. stub 演示脚本（验证 US1/US2/US3）

运行示例脚本（实现阶段交付于 `examples/demo_mcp_client.py`）：

```bash
python examples/demo_mcp_client.py
```

**预期输出依次包含**:

1. 以 stdio 传输连接一个本地测试用 MCP server，握手成功；
2. 通过 `tools/list` 发现该 server 暴露的工具（`echo`/`slow`/`fail`），
   全部注册进 `ToolRegistry`；
3. 调用 `echo` 工具，返回透传的参数内容；
4. 以 HTTP 传输连接另一个（同逻辑）测试用 MCP server，重复 1-3 步骤，
   证明调用方无法区分底层传输方式；
5. 调用 `slow` 工具触发调用超时，识别为 `McpTimeoutError`；
6. 调用 `fail` 工具触发业务失败，识别为 `McpToolExecutionError`；
7. 主动断开一个连接后再次调用其工具，识别为 `McpDisconnectedError`，
   同时验证另一个连接的工具仍可正常调用（失败隔离）；
8. 每次连接/调用的 console span 输出，含 `tenant_id`/`transport`/
   `tool_name`/`result_type`。

## 验证清单对照

| 验证项 | 步骤 | 对应 |
|--------|------|------|
| 新连接工具无需专用适配代码即可被调用 | 2-③ | SC-001 |
| stdio/HTTP 两种传输发现与调用行为等价 | 2-④ | SC-001/SC-002（对应 spec US2 验收） |
| 握手/发现/调用全部有超时上限，无无限期挂起 | 2-⑤ | SC-003 |
| 单个连接失败/断开不影响其他已注册工具 | 2-⑦ | SC-004 |
| 15 分钟内完成 1+2 | 计时 | 效率基线（同 001-005 惯例） |
