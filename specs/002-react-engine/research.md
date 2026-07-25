# Research: ReAct 引擎

**Date**: 2026-07-25 | **Plan**: [plan.md](plan.md)

## R1. "思考"结果的表达格式（最终答案 vs 工具调用决策）

- **Decision**: 要求 provider 返回结构化 JSON（通过 system 提示约束输出格式），
  形如 `{"action": "final_answer", "content": "..."}` 或
  `{"action": "call_tool", "tool": "<name>", "arguments": {...}}`。
  解析失败（非 JSON、缺 `action` 字段、`action` 值非法）按"格式错误的思考结果"
  处理——转成一次失败的观察结果反馈给下一轮（消耗一个步数），不是让整个运行崩溃
  （与 FR-005"工具失败转观察"同等对待格式错误，因为两者都是"这一步没有产出有效行动"）。
- **Rationale**: 结构化输出是 ReAct 实现的标准做法（比正则解析自由文本可靠）；
  provider 本身不关心格式（只传消息、拿字符串内容），格式约束完全在 react
  层的 prompting 模块完成，不侵入 provider 契约。
- **Alternatives considered**: 依赖模型原生 function-calling 字段（需 provider
  暴露厂商特定字段，违反"provider 只提供统一响应结构"的 001 契约）；
  ReAct 经典的 `Thought:/Action:/Observation:` 纯文本格式（解析更脆弱，
  对非英语输出更不稳定）。

## R2. 步数计数规则

- **Decision**: 步数在"思考"发生时计数（无论该步最终是回答还是调用工具）。
  `max_steps=N` 表示最多进行 N 次思考。第 N 次思考若仍未给出最终答案
  （无论是决定调用工具还是思考结果格式错误），运行终止并返回步数耗尽结果。
- **Rationale**: 与 spec 验收场景 US2-3 一致（`max_steps=1` 时第一步决定调用
  工具即立即终止，不"多跑一步"去处理观察结果）——即工具调用的观察反馈会被
  计入下一次思考的输入，但下一次思考本身就是第 N+1 步，若已达上限则不发生。
- **Alternatives considered**: 步数在"工具调用"发生时计数（会导致"直接回答"
  路径永远不消耗步数预算，语义不一致）。

## R3. Provider 异常 vs 步数耗尽的边界

- **Decision**: `ReactEngine.run()` 对 provider 抛出的 `ProviderError`
  子类（001 已定义）不捕获、原样向上传播，中断当前运行。只有"到达
  max_steps 仍未产出最终答案"才返回本 feature 新定义的
  `StepBudgetExceededError`。
- **Rationale**: spec Edge Cases 明确要求两者可区分——步数耗尽是"引擎认为
  目标本身太复杂/工具不够用"，provider 异常是"底层调用失败"（超时/超限/
  连接问题），调用方的补救策略完全不同（前者可能需要更换策略或增加步数，
  后者是基础设施问题）。
- **Alternatives considered**: 把 provider 异常也包装成一种"观察结果"重试
  （违反 FR-007，且会让超时/成本超限被无意义地反复触发，与宪法原则 IV 的
  精神相悖——多消耗一次失败调用的 token/成本代价）。

## R4. 工具调用失败的三种来源与统一处理

- **Decision**: 定义 `Observation` 结构统一表达三种情形——
  (a) 工具名未在传入的工具集合中注册，(b) `tool.invoke()` 抛出任意异常，
  (c) 工具正常返回但业务上表示失败（此情形工具自身在返回内容中说明，
  引擎不做特殊识别，交给下一轮思考判断）。(a)(b) 由引擎捕获并生成
  `Observation(success=False, content=<说明>)`；成功调用生成
  `Observation(success=True, content=<工具返回值>)`。
- **Rationale**: 收敛为一种数据结构而不是三套异常处理路径，符合最简原则；
  `success` 布尔字段让下一轮的提示构造可以统一处理"要不要告诉模型这步失败了"。
- **Alternatives considered**: 为三种情形定义三个不同异常类型
  （过度设计——调用方/下一轮思考并不需要区分是"未注册"还是"抛异常"，
  都是"这个工具这次没给出可用结果"）。

## R5. 遥测标注的实现方式

- **Decision**: 复用 001 `kernel.provider.telemetry` 中已有的 tracer
  （`kernel.provider` tracer name），在 engine 每步循环体内用同一 tracer
  开一个 `react.step` span，属性含 `react.step.index`（从 1 开始）、
  `react.step.action`（`final_answer` / `call_tool` / `malformed`）、
  `react.step.tool_name`（仅工具调用步）；该 span 作为该步内 provider 调用
  span 的父 span（用 OTel context 关联），审计时可从父 span 下钻到具体的
  LLM 调用明细。
- **Rationale**: 复用同一 tracer 避免引入第二个 TracerProvider 配置面；
  父子 span 关系是 OTel 原生能力，比额外维护"运行 ID"字符串串联更可靠。
  遥测异常处理沿用 001 telemetry 模块已验证的"try/except + warning 日志"模式。
- **Alternatives considered**: 引擎自建独立 tracer name（`kernel.react`）
  ——分析后认为父子 span 场景下用同一 tracer 更符合 OTel 惯例，且避免
  两套 tracer 配置的维护成本。

## R6. Stub provider 的测试驱动方式

- **Decision**: 测试用一个「脚本化响应队列」包裹真实 `LLMProvider`
  （复用 001 的 `httpx.MockTransport`），按调用顺序依次返回预设的
  JSON 字符串（如 `["调用工具", "最终答案"]`），验证引擎按序驱动。
- **Rationale**: 复用 001 已验证的 stub 机制（同一套 `MockTransport` 模式），
  不新增测试基础设施类型；"脚本化响应队列"只是 001 conftest 中
  `success_transport(payload)` 的多次调用组合，零新依赖。
- **Alternatives considered**: 为 react 测试单独 mock 一个假的
  `LLMProvider` 类（跳过真实 provider 逻辑）——会削弱"engine 正确使用
  provider 公共契约"的验证力度，选择复用真实 provider + stub transport。
