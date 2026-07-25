# Research: 内核骨架与 provider 模块

**Date**: 2026-07-25 | **Plan**: [plan.md](plan.md)

本文档记录 Technical Context 中各项决策及理由。所有 NEEDS CLARIFICATION 已消解。

## R1. 语言与运行时

- **Decision**: Python 3.12
- **Rationale**: LLM 生态最成熟——LiteLLM、OTel GenAI 语义约定、Langfuse SDK
  均以 Python 支持最好；开发迭代最快。用户已确认。
- **Alternatives considered**: TypeScript/Node（异步 IO 好但 GenAI 遥测生态薄）、
  Go（并发与部署强但 agent 生态最薄、开发最慢）。

## R2. 同步 vs 异步 API

- **Decision**: provider 公共接口为 async（`async def complete(...)`），
  基于 `httpx.AsyncClient`。
- **Rationale**: LLM 调用是长耗时 IO（秒级），多租户 runtime 必然并发；
  同步接口日后翻异步是破坏性接口变更（违反"不破坏既有契约"），
  一开始就 async 反而是最简路径。react 等后续模块以 async 为基准设计。
- **Alternatives considered**: 同步接口（更简单但并发时需线程池，且日后必改接口）；
  同时提供 sync + async 双接口（维护两套，违反原则 II）。

## R3. 请求/响应结构

- **Decision**: 标准库 `dataclasses`（frozen），手写参数校验函数。
- **Rationale**: 不新增依赖（原则 II/III）；字段少（<10 个），
  手写校验代码量与 pydantic 声明相当，还能给出精确的中文错误信息。
- **Alternatives considered**: pydantic v2（校验强但引入重依赖，且校验错误
  类型与我们的异常层级重复）；TypedDict（无运行时校验）。

## R4. 错误模型

- **Decision**: 异常层级——`ProviderError` 基类 + 6 个子类：
  `InvalidRequestError`、`CallTimeoutError`、`TokenLimitExceededError`、
  `CostLimitExceededError`、`ProxyConnectionError`、`MalformedResponseError`。
- **Rationale**: 异常是 Python 惯用错误模型，调用方可 `except` 精确分类
  （满足 FR-005"可编程区分"）；每个异常携带诊断字段（实际值/上限值）。
- **Alternatives considered**: Result/Either 返回值（非 Python 惯用，
  调用方容易忽略错误分支）。

## R5. LiteLLM 集成方式

- **Decision**: 独立部署的 LiteLLM proxy，provider 仅通过其 OpenAI 兼容
  HTTP 接口（`POST /v1/chat/completions`，非流式）通信。base_url 由构造参数注入。
- **Rationale**: 用户已拍板 proxy 模式；符合原则 III（网络 API 集成、不改源码、
  可替换）。provider 对 proxy 的依赖收敛为一个 HTTP 契约
  （见 [contracts/litellm-proxy-contract.md](contracts/litellm-proxy-contract.md)），
  测试用 `httpx.MockTransport` 直接模拟该契约。
- **Alternatives considered**: litellm 作为 Python 库内嵌（简单但属库依赖，
  路由配置分散到各内核实例，多租户限额无法集中管理）。

## R6. 测试 stub 方案

- **Decision**: `httpx.MockTransport` + 手写响应工厂；span 断言用 OTel SDK 自带
  `InMemorySpanExporter`。
- **Rationale**: 两者均为已有依赖的内置能力，零新增依赖；MockTransport
  可精确模拟慢响应（超时）、畸形响应、连接异常。
- **Alternatives considered**: respx（好用但新增依赖）；起本地真实 HTTP server
  （慢、端口管理复杂，违反"单元测试无网络"）。

## R7. OTel GenAI span 约定

- **Decision**: 手动创建 span，命名 `chat {model}`；属性采用 GenAI 语义约定
  （`gen_ai.operation.name`、`gen_ai.request.model`、`gen_ai.response.model`、
  `gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`）+ 项目扩展属性
  `tenant_id`、`gen_ai.usage.cost`。失败时 span status = ERROR 并记录异常类型。
  span 发出包裹在 try/except 中，遥测异常只记日志不上抛（FR-007）。
- **Rationale**: GenAI 语义约定目前处于 incubating 阶段，手动打点比依赖
  auto-instrumentation 包更稳定可控；`tenant_id` 是宪法钦定属性名。
- **Alternatives considered**: `opentelemetry-instrumentation-httpx` 自动埋点
  （只有 HTTP 维度，无 gen_ai 语义与 tenant 维度）；Langfuse SDK 直采
  （绑定单一后端，违反组装可替换原则——Langfuse 应作为 OTel 后端接入，属平台层配置）。

## R8. 成本计算与安全默认值

- **Decision**: 本地计算：`cost = input_tokens/1000 × 输入单价 + output_tokens/1000 × 输出单价`。
  单价表（`PriceTable`）由构造参数注入；模型无单价 → 调用前抛 `InvalidRequestError`。
  安全默认值：超时 60 秒、token 上限 8192（输入+输出合计）、单次成本上限 0.50 USD。
  三者均可按请求覆盖，但取值必须为正数——不存在"无限制"取值。
- **Rationale**: proxy 侧虽也能算成本，但本地计算不依赖 proxy 版本行为，
  且成本上限必须在内核强制（宪法 IV）。默认值保守：60s 覆盖绝大多数非流式调用；
  0.50 USD 在主流模型上足够单次 agent 步骤使用，失控时损失可控。
- **Alternatives considered**: 信任 proxy 返回的 `x-litellm-response-cost` 头
  （耦合 LiteLLM 私有行为，换路由组件即失效——记录为未来优化项，可作交叉校验）。

## R9. token 上限执行方式

- **Decision**: 双侧执行——请求侧把剩余预算作为 `max_tokens`（输出上限）传给 proxy；
  响应侧校验 `usage.total_tokens` 不超过请求的 token 上限，超出抛
  `TokenLimitExceededError`。输入消息在发出前本地估算（字符数/4 粗估）,
  明显超预算直接拒绝。
- **Rationale**: 仅靠请求侧无法防御 proxy/模型不遵守 max_tokens 的情况；
  仅靠响应侧则钱已花出。粗估输入避免引入 tokenizer 依赖（原则 II），
  精确计数留给未来需要时再议。
- **Alternatives considered**: 引入 tiktoken 精确计数（新增依赖且绑定 OpenAI
  分词器，对多模型不准）。

## R10. 骨架接口形态（react/memory/tool）

- **Decision**: 用 `typing.Protocol` 定义接口 + 一个最小占位实现；
  react 接口签名包含 `max_steps: int` 必填参数（为宪法 VI 预留）。
- **Rationale**: Protocol 是结构化鸭子类型，后续实现无需继承内核基类，
  耦合最低；占位实现保证骨架可实例化、可测试（US4）。
- **Alternatives considered**: ABC 抽象基类（强制继承，耦合高）；
  只写文档不写接口（骨架无法被测试锁定）。
