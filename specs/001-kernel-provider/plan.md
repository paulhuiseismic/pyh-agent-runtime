# Implementation Plan: 内核骨架与 provider 模块

**Branch**: `001-kernel-provider` | **Date**: 2026-07-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-kernel-provider/spec.md`

## Summary

建立 agent 内核四模块（provider/react/memory/tool）的 Python 包骨架与接口定义，
完整实现 provider：经 LiteLLM proxy（OpenAI 兼容 HTTP 接口）完成 LLM 调用，
每次调用强制显式超时、token 上限、成本上限（超限抛类型化异常），
并发出符合 OTel GenAI 语义约定、必带 `tenant_id` 的 span。
react/memory/tool 仅交付接口（Protocol）与占位实现。
测试全部基于 `httpx.MockTransport` 本地 stub，零外部依赖。

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: httpx（HTTP 客户端，显式超时）、opentelemetry-sdk +
opentelemetry-api（span 发出）；标准库 dataclasses 做请求/响应结构（不引入 pydantic）

**Storage**: N/A（本 feature 无持久化）

**Testing**: pytest + pytest-asyncio；LiteLLM proxy 以 `httpx.MockTransport` 模拟，
span 以 OTel `InMemorySpanExporter` 断言

**Target Platform**: Linux server / 本地开发（Windows/macOS 均可运行测试）

**Project Type**: library（内核为独立可测试的 Python 包）

**Performance Goals**: 单次调用的内核自身开销 <10ms（参考值，不设基准测试门禁——
LLM 调用秒级耗时下内核开销非瓶颈）；支持 asyncio 并发调用互不串扰

**Constraints**: 任何限额不允许"无限制"；遥测失败不影响调用；
内核零平台层依赖、零厂商 SDK 依赖

**Scale/Scope**: 本 feature 约 6-8 个源文件 + 单元测试；接口需承载后续
react/memory/tool 实现与平台层接入

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | 内核包 `kernel/` 不 import 任何平台层代码（平台层尚不存在）；测试无平台组件即可运行 | ✅ 通过 |
| II. 最简实现 | 用 dataclass + 异常层级 + 单个 client 类；不引入 pydantic、不做重试框架、不做插件机制 | ✅ 通过 |
| III. 组装优先 | 路由用 LiteLLM proxy（网络 API，不改源码）；license 登记 THIRD_PARTY.md（FR-010） | ✅ 通过 |
| IV. 超时与成本上限 | httpx 显式 timeout 必填；token/成本上限有安全默认值，超限抛类型化异常 | ✅ 通过 |
| V. OTel GenAI 可观测 | 每次调用（含失败）发 gen_ai span，`tenant_id` 必带，缺失拒绝调用 | ✅ 通过 |
| VI. 测试与安全边界 | provider 全场景单测（FR-009）；ReAct 最大步数属后续 feature，本次仅在接口中预留 `max_steps` 参数 | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物（data-model/contracts/quickstart）未引入新依赖
或新抽象，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/001-kernel-provider/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── provider-api.md          # 内核对上层暴露的 Python 接口契约
│   └── litellm-proxy-contract.md # provider 依赖的 proxy HTTP 契约子集
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
pyproject.toml           # 包定义（kernel 包 + dev 依赖）
THIRD_PARTY.md           # 第三方组件 license 登记（FR-010）

src/kernel/
├── __init__.py
├── provider/
│   ├── __init__.py      # 导出公共接口
│   ├── models.py        # LLMRequest / LLMResponse / Limits / PriceTable (dataclasses)
│   ├── errors.py        # ProviderError 异常层级（6 类）
│   ├── pricing.py       # 成本计算（单价表 × 用量）
│   ├── telemetry.py     # GenAI span 发出（tenant_id 必带；失败不影响调用）
│   └── client.py        # LLMProvider：校验 → 调 proxy → 限额检查 → 发 span
├── react/
│   └── __init__.py      # ReactLoop Protocol（含 max_steps）+ 占位实现
├── memory/
│   └── __init__.py      # Memory Protocol + 占位实现
└── tool/
    └── __init__.py      # Tool Protocol + 占位注册表

examples/
├── demo_stub.py         # stub 演示（quickstart 第 2 节）
└── demo_proxy.py        # 真实 proxy 演示（quickstart 第 3 节，可选）

tests/unit/
├── provider/
│   ├── test_client_success.py    # US1：成功调用、模型参数传递
│   ├── test_client_limits.py     # US2：超时/token/成本超限、默认值
│   ├── test_client_validation.py # US1/US2：参数校验（缺 tenant_id、非法限额、无单价）
│   ├── test_client_errors.py     # 边界：连接失败、响应格式错误
│   └── test_telemetry.py         # US3：span 属性、失败调用 span、遥测失败不影响调用
└── test_kernel_skeleton.py       # US4：四模块可实例化、零平台依赖
```

**Structure Decision**: 单包 library 布局（src layout）。`kernel` 为顶层包，
四模块为其子包；平台层未来以独立包（如 `platform/`）加入，只允许平台 → kernel
单向依赖。provider 内部按职责拆 5 个文件，不再细分。

## Complexity Tracking

> 无违宪项，本表为空。
