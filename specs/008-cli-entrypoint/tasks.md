---

description: "Task list for CLI 入口（复用平台服务层）"
---

# Tasks: CLI 入口（复用平台服务层）

**Input**: Design documents from `/specs/008-cli-entrypoint/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md；依赖 007（`platform_service.config/auth/agent_service/
telemetry` 零改动复用；不依赖 `scheduler.py`，见 research.md R3）

**Tests**: 包含测试任务——宪法附加约束要求平台层新增代码附带单元测试
（呼应原则 VI 精神）。全部测试均可在无外部网络、无真实模型密钥的情况下
运行（复用 001/007 已确立的 `httpx.MockTransport` stub 模式）；仅一个
打包冒烟测试通过真实子进程调用模块，不依赖网络。

**Organization**: 按用户故事分组；US1（核心调用与结果）是 MVP 且独立可测，
其实现天然需要一次性接入 007 的鉴权/超时全部环节（`cli.run()` 是单一
内聚函数，无法有意义地拆分为"半成品"）；US2（身份/配置错误清晰反馈）
在 US1 已完整实现的错误分支之上补充针对性验证；US3（遥测贯通）在
`cli.py` 中补充 `platform.request` span 包裹并验证租户标识贯穿。

> **`/speckit-analyze` F1 修正说明**：初版设计曾计划让 `cli.run()` 复用
> 007 的 `ConcurrencyScheduler`，但单进程单次调用场景下，一个全新构造的
> 调度器的首次 `try_acquire` 必然成功（`max_concurrent_requests`/
> `global_max_concurrent_requests` 恒为正整数），`EXIT_CONCURRENCY_EXCEEDED`
> 在生产环境下不可能被触发，属于"为未来假设场景预留"的过度设计，
> 违反宪法原则 II；且该测试（预先占满调度器状态）也因调度器实例无法
> 从外部注入而根本无法实现。已从本任务列表、spec.md/data-model.md/
> contracts/research.md 中移除该分支与对应退出码，详见 research.md R3。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

不新建顶层包——新增文件全部落入既有 `src/platform_service/`（新增
`cli.py`）与 `tests/unit/platform_service/`（新增 `test_cli.py`/
`test_cli_telemetry.py`），见 plan.md Structure Decision。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 声明打包入口，无新增依赖

- [X] T001 在 pyproject.toml 的 `[project.scripts]` 新增
      `pyh-agent = "platform_service.cli:main"`（无新增第三方依赖，
      `argparse` 为标准库）；不在本任务做人工可用性验证，统一放到
      Polish 阶段的 T014 一次性验证（避免与 T014 重复执行同一步骤）

**Checkpoint**: pyproject.toml 声明已保存，`git diff` 可见新增的
`[project.scripts]` 段落

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 退出码常量、参数解析、API Key 读取——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T002 创建 src/platform_service/cli.py 骨架：按
      contracts/cli-contract.md 定义退出码常量
      `EXIT_SUCCESS=0`/`EXIT_MISSING_API_KEY=1`/`EXIT_AUTH_FAILED=2`/
      `EXIT_CONFIG_INVALID=3`/`EXIT_VALIDATION_FAILED=4`/
      `EXIT_TIMEOUT=5`/`EXIT_KERNEL_ERROR=6`；
      `build_arg_parser() -> argparse.ArgumentParser`——位置参数 `goal`、
      可选 `--session-id`、可选 `--config`；
      `resolve_api_key(env: Mapping[str, str]) -> str | None`——读取
      `PLATFORM_SERVICE_API_KEY`，未设置或为空返回 `None`
- [X] T003 [P] 更新 src/platform_service/__init__.py：追加导出
      `platform_service.cli` 模块的 `main` 函数（供
      `python -m platform_service.cli` 与测试直接 import 引用）
- [X] T004 [P] 创建 tests/unit/platform_service/test_cli.py 骨架：
      验证 `build_arg_parser()` 正确解析
      `["问题", "--session-id", "s1", "--config", "c.json"]`；
      验证 `resolve_api_key({})` 返回 `None`，
      `resolve_api_key({"PLATFORM_SERVICE_API_KEY": "k"})` 返回 `"k"`

**Checkpoint**: `pytest tests/unit/platform_service/test_cli.py` 全绿
（仅覆盖骨架部分）

---

## Phase 3: User Story 1 - 通过命令行发起一次 agent 调用并获得结果 (Priority: P1) 🎯 MVP

**Goal**: 一条命令对应一次完整调用，成功时标准输出打印结果并成功退出，
内核处理失败/超时时明确失败退出，同一会话标识跨命令延续上下文

**Independent Test**: 用 stub provider 驱动 `cli.run()`，验证成功场景
返回 `(EXIT_SUCCESS, answer文本, "")`；驱动一次内核失败与一次超时场景
验证对应退出码；对同一 `session_id` 连续两次调用 `run()` 验证第二次
结果体现第一次积累的会话上下文——全程不依赖 US2 的错误消息断言、US3 的
span 断言

- [X] T005 [US1] 在 src/platform_service/cli.py 实现
      `async def run(argv: list[str], env: Mapping[str, str], *,
      agent_service: AgentService | None = None) -> tuple[int, str, str]`：
      1) `build_arg_parser().parse_args(argv)`；2) 解析
      `config_path = args.config or env.get("PLATFORM_SERVICE_CONFIG")`，
      缺失时返回 `(EXIT_CONFIG_INVALID, "", "错误: 未提供配置文件路径...")`；
      3) `load_config_from_file(config_path)` 捕获
      `FileNotFoundError`/`json.JSONDecodeError`/`KeyError`/
      `InvalidRequestError`，统一映射为 `EXIT_CONFIG_INVALID`；
      4) `resolve_api_key(env)` 为 `None` 时返回
      `(EXIT_MISSING_API_KEY, ...)`；5) `resolve_tenant(api_key, config)`
      捕获 `AuthenticationError` 映射 `EXIT_AUTH_FAILED`；6) `args.goal`
      去空白后为空时返回 `EXIT_VALIDATION_FAILED`；7) `agent_service`
      参数未提供时 `await build_agent_service(config)` 构造一次（生产
      路径，不经过 `ConcurrencyScheduler`，research.md R3）；8)
      `asyncio.wait_for(service.handle(AgentRunRequest(goal=args.goal,
      session_id=args.session_id), tenant_id=tenant_id),
      timeout=config.request_timeout_seconds)`——`asyncio.TimeoutError`
      映射 `EXIT_TIMEOUT`，其余异常映射 `EXIT_KERNEL_ERROR`；9)
      成功时返回 `(EXIT_SUCCESS, result.answer + "\n", "")`（暂不含
      `platform.request` span 包裹，US3 补全，research.md R6）
- [X] T006 [US1] 在 src/platform_service/cli.py 实现
      `def main() -> None`：`asyncio.run(run(sys.argv[1:], os.environ))`，
      把返回的 stdout/stderr 文本分别写入 `sys.stdout`/`sys.stderr`
      （非空时），以返回的退出码调用 `sys.exit()`
- [X] T007 [P] [US1] 在 tests/unit/platform_service/test_cli.py 补充：
      成功调用（stub provider）验证返回
      `(EXIT_SUCCESS, "42\n", "")`（复用 conftest `stub_provider`）；
      内核处理失败（`erroring_provider`）验证返回 `EXIT_KERNEL_ERROR`
      且 stderr 非空；请求超时（`slow_stub_provider` + 极短
      `request_timeout_seconds`）验证返回 `EXIT_TIMEOUT`
- [X] T008 [P] [US1] 在 tests/unit/platform_service/test_cli.py 补充：
      对同一 `session_id`、指向同一临时数据库文件路径的
      `PlatformConfig`，连续两次调用 `run()`（模拟两次独立命令执行），
      验证第二次的 `AgentRunResult`/输出体现第一次调用积累的会话历史
      （复用 stub provider 按调用次数返回不同内容，断言第二次请求发给
      provider 的内容包含第一次的历史文本）
- [X] T009 [P] [US1] 在 tests/unit/platform_service/test_cli.py 补充一个
      标记为 `smoke` 的测试（`@pytest.mark.smoke` 或函数名含 `smoke`）：
      用 `subprocess.run([sys.executable, "-m", "platform_service.cli"],
      ...)` 不带任何参数/环境变量调用，验证进程以 `EXIT_MISSING_API_KEY`
      或 argparse 参数错误退出（非 0），确认模块可作为独立子进程被调用
      （验证打包链路，不依赖网络，不依赖 `pyh-agent` 是否已注册为控制台
      命令）

**Checkpoint**: US1 测试全绿——MVP 可演示（命令行 → `AgentService` 组合
内核能力 → 终端输出结果的完整闭环，含核心失败分类与会话延续）

---

## Phase 4: User Story 2 - 未正确配置租户身份或平台配置时给出清晰反馈 (Priority: P2)

**Goal**: 缺少 API Key、API Key 不匹配租户、配置文件缺失/无效三种情形，
均在触发任何内核调用之前失败退出，且失败原因彼此可区分

**Independent Test**: 分别构造"未设置 API Key 环境变量"
"API Key 不匹配任何租户""配置文件路径不存在"三种输入，独立验证
`cli.run()` 均在到达 `AgentService` 之前返回，且退出码与 stderr 文本
彼此不同

> T005 已实现全部相关分支（本阶段不修改 `cli.py` 的控制流），本阶段
> 聚焦于验证这些分支的退出码与错误文本满足"彼此可区分"的验收标准，
> 如断言发现文本不够清晰会在本阶段task中直接修正 T005 产出的提示文案。

- [X] T010 [US2] 在 tests/unit/platform_service/test_cli.py 补充：
      未设置 `PLATFORM_SERVICE_API_KEY` 环境变量 → 验证返回
      `(EXIT_MISSING_API_KEY, "", <非空 stderr>)`（验收场景 US2-1）；
      设置了一个不属于任何租户的 API Key → 验证返回
      `(EXIT_AUTH_FAILED, "", <非空 stderr>)`，且该 stderr 文本与上一条
      不同（验收场景 US2-2）；`--config` 指向不存在的文件 → 验证返回
      `(EXIT_CONFIG_INVALID, "", <非空 stderr>)`（验收场景 US2-3）；
      `goal` 为空字符串 → 验证返回
      `(EXIT_VALIDATION_FAILED, "", <非空 stderr>)`（Edge Case）；
      以上四种失败均需断言 stub `AgentService` 未被调用（如通过传入一个
      会在被调用时抛出断言错误的哨兵 `agent_service` 双重验证"未触发
      任何内核调用"）

**Checkpoint**: US1+US2 测试全绿——身份识别与配置校验相关的失败反馈清晰
可区分，且均先于内核调用发生

---

## Phase 5: User Story 3 - 命令执行结果的可观测性与租户标识贯穿 (Priority: P3)

**Goal**: 一次成功的 CLI 调用触发的全部内核可观测记录都携带与本次调用
一致的租户标识，与 007 REST 入口的可观测性行为一致

**Independent Test**: 用 in-memory span exporter 驱动一次成功的
`cli.run()` 调用，验证产生的 `platform.request` 根 span 与其下内核
`chat {model}`/`react.step` 子 span 均携带一致的 `tenant_id`

- [X] T011 [US3] 在 src/platform_service/cli.py 的 `run()` 中，用
      `platform_service.telemetry.platform_request_span(tenant_id=...,
      session_id=...)`（复用 007 既有实现，零改动）包裹 T005 第 8 步的
      `asyncio.wait_for(...)` 调用，各退出分支对应设置
      span 的 `result`（success/timeout/kernel_error），与 007 `app.py`
      的既有用法完全一致（research.md R6）
- [X] T012 [P] [US3] 创建 tests/unit/platform_service/test_cli_telemetry.py：
      用 `InMemorySpanExporter` 驱动一次成功的 `run()` 调用，断言
      `platform.request` span 携带正确 `tenant_id`，其下 `react.step`/
      `chat {model}` 子 span 与之 trace_id 一致、父子关系正确（复用 007
      `test_telemetry.py` 的断言风格）；未设置 API Key 的调用验证不产生
      任何 span（与 007 未鉴权请求行为一致）

**Checkpoint**: US1-US3 测试全绿——CLI 入口的调用、错误反馈、可观测性
全部具备，与 007 REST 入口行为对齐

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 演示脚本、文档收尾与最终验证

- [X] T013 [P] 创建演示脚本 examples/demo_cli.py：复用
      examples/platform_config.example.json 结构（provider 替换为 stub，
      避免需要真实模型密钥），依次演示成功调用、缺少 API Key、身份识别
      失败、内核失败四个场景，直接调用 `cli.run()` 并打印返回的退出码/
      输出内容
- [X] T014 按 quickstart.md 全流程验证：
      `pytest tests/unit/platform_service -v` 全绿（含新增的 `test_cli.py`/
      `test_cli_telemetry.py`）→ demo 脚本输出符合预期 → 执行
      `pip install -e .` 后运行 `pyh-agent --help` 确认控制台命令可用
      （T001 声明的打包入口在此一次性验证）→ 修复发现的问题
- [X] T015 更新 README.md roadmap：008 状态改为"✅ 已完成"；更新
      examples/README.md 追加 `demo_cli.py` 条目

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：依赖 Phase 2 全部任务，是 US2/US3 的基础（`cli.py` 的
  `run()`/`main()` 均在 US1 建立）
- **US2**：依赖 US1 已实现的完整错误分支（`cli.py` 本阶段不做代码改动，
  仅补充验证与必要的文案修正）
- **US3**：依赖 US1 建立的 `run()` 主流程，在其上包裹遥测 span
  （不影响已有的退出码/输出行为）
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T003/T004 并行（T002 先行）
- US1 内：T007/T008/T009 均落在同一个 test_cli.py 文件，但各自新增独立
  测试函数，可并行编写（不修改同一函数体，仅同文件追加）
- US2 内：T010 单任务，依赖 T005
- US3 内：T012 依赖 T011
- Phase 6：T013 可与 T011/T012 并行准备；T014 依赖 T013；T015 依赖 T014

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T009）：命令行 → `AgentService` 组合
内核能力 → 终端输出结果的完整闭环即可演示核心价值，已包含超时/会话
延续（因 `run()` 是不可有意义拆分的单一内聚函数；不含并发调度，
research.md R3）。随后 US2（错误反馈清晰度验证）→ US3（遥测贯通）
递增交付，最后 Polish 补齐演示脚本与文档。每个 Checkpoint 处 `pytest`
必须全绿再前进。
