# THIRD_PARTY

第三方组件 license 登记（宪法原则 III：引入前记录 license）。

| 组件 | License | 集成方式 | 约束说明 |
|------|---------|----------|----------|
| LiteLLM (proxy) | MIT（开源核心） | 独立部署，仅经 OpenAI 兼容 HTTP API 集成，不修改源码 | 仅使用核心功能（路由、限额）；`enterprise/` 目录功能为商业 license，禁止使用 |
| httpx | BSD-3-Clause | Python 库依赖 | — |
| OpenTelemetry Python (opentelemetry-api / opentelemetry-sdk) | Apache-2.0 | Python 库依赖 | — |
| pytest / pytest-asyncio | MIT / Apache-2.0 | dev 依赖，不进入生产分发 | — |
| aiosqlite | MIT | Python 库依赖（memory 模块的异步 SQLite 驱动） | — |
| mcp（官方 Model Context Protocol Python SDK） | MIT | Python 库依赖（tool 模块的 MCP 客户端协议实现，006） | 仅使用 client 侧（`ClientSession`/`stdio_client`/`streamablehttp_client`）与测试用 `FastMCP`，不修改源码 |
