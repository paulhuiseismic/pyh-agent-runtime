---

description: "Task list for plugin tool 插件机制 + sandbox"
---

# Tasks: plugin tool 插件机制 + sandbox

**Input**: Design documents from `/specs/005-tool-plugin-sandbox/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`Tool` Protocol、`InvalidRequestError` 已交付）、002（`ReactEngine` 兼容性验证）

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试（FR-012），
不适用模板的"测试可选"约定。CPU/内存资源限制相关测试在非 POSIX 平台用
`pytest.mark.skipif` 显式跳过并注明原因（research.md R2），不是遗漏。

**Organization**: 按用户故事分组；US1（注册中心）独立；US2（沙箱成功/业务失败路径）
与 US3（超时/资源超限）均在 `sandbox.py` 上演进，US2 先行建立执行框架，
US3 补全限额判定。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

延续 001-004 的单包 library 布局：`src/kernel/tool/`、`tests/unit/tool/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 目录骨架与测试用示例脚本，全部后续任务的前提

- [X] T001 创建目录骨架：tests/unit/tool/ 目录、tests/unit/tool/__init__.py、
      tests/unit/tool/fixtures/ 目录
- [X] T002 [P] 创建测试用示例脚本 tests/unit/tool/fixtures/echo_args.py：
      从 stdin 读取 JSON 参数，原样打印到 stdout 后正常退出（exit 0）
- [X] T003 [P] 创建测试用示例脚本 tests/unit/tool/fixtures/sleep_forever.py：
      不读取 stdin，sleep 一个远超测试超时配置的时长（用于触发超时）
- [X] T004 [P] 创建测试用示例脚本 tests/unit/tool/fixtures/exit_nonzero.py：
      打印一段说明文字到 stderr 后以非零退出码（如 1）退出
- [X] T005 [P] 创建测试用示例脚本 tests/unit/tool/fixtures/grow_memory.py：
      持续分配内存直至超过一个明显较大的阈值（仅供 POSIX 资源超限测试使用，
      Windows 测试中不会执行到这个脚本）

**Checkpoint**: `pytest tests/unit/tool -q` 可运行（0 tests，示例脚本尚未被引用）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构、异常层级、运行器脚本与测试设施——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T006 实现配置与异常 src/kernel/tool/sandbox_models.py：frozen dataclass
      SandboxLimits（timeout_seconds=30.0/max_cpu_seconds=10.0/
      max_memory_bytes=256MB/max_output_bytes=1MB，均校验为正数，
      非正数抛 InvalidRequestError）；异常层级 SandboxError/SandboxInfraError/
      SandboxTimeoutError/SandboxResourceExceededError/SandboxStartupError/
      SandboxToolExecutionError（各携带诊断字段，data-model.md）
- [X] T007 [P] 实现沙箱运行器 src/kernel/tool/sandbox_runner.py：
      作为独立可执行模块（`python -m kernel.tool.sandbox_runner <command...>`），
      POSIX 上用 resource.setrlimit 设置 RLIMIT_CPU/RLIMIT_AS 后 os.execvp
      替换为目标命令；非 POSIX（sys.platform != 支持资源限制的平台）跳过
      限制设置直接 execvp（research.md R1/R2）；execvp 抛出
      OSError/FileNotFoundError/PermissionError 时捕获并打印诊断到 stderr，
      以保留退出码 127 退出（父进程识别协议见 data-model.md"运行器 ↔ 父进程
      的失败识别协议"一节，不能跨进程捕获异常）
- [X] T008 [P] 创建测试公共设施 tests/unit/tool/conftest.py：示例脚本绝对路径
      fixture（拼接 sys.executable + fixtures/*.py）、SandboxLimits 短超时
      fixture（供超时类测试使用较小的 timeout_seconds 加速测试）
- [X] T009 [P] SandboxLimits 与异常层级单元测试 tests/unit/tool/test_sandbox_models.py：
      默认值正确、非正数字段被拒绝；各异常类的诊断字段可正确构造与读取

**Checkpoint**: `pytest tests/unit/tool/test_sandbox_models.py` 全绿

---

## Phase 3: User Story 1 - 注册与查找工具 (Priority: P1) 🎯 MVP

**Goal**: 按名称注册/查找/列出工具，重名拒绝，未找到不抛异常

**Independent Test**: 用几个满足 Tool Protocol 的简单示例工具驱动
ToolRegistry 的注册/查找/列出，全程不需要沙箱执行或平台层组件

- [X] T010 [US1] 实现工具注册中心 src/kernel/tool/registry.py：ToolRegistry
      类——register(tool) 重名抛 InvalidRequestError（复用 001 异常，
      research.md R6）、get(name) 未找到返回 None、list_tools()、
      as_dict()（供 002 ReactEngine(tools=...) 直接使用，contracts）
- [X] T011 [P] [US1] 注册与查找单元测试 tests/unit/tool/test_registry.py：
      注册后可按名称查到且出现在 list_tools（验收场景 US1-1）；重名注册
      被拒绝、原工具不变（验收场景 US1-2）；同时注册可信实现与沙箱插件
      互不影响查找（验收场景 US1-3）；查找未注册名称返回 None 不报错
      （验收场景 US1-4）

**Checkpoint**: US1 测试全绿——MVP 可演示（工具的统一注册与查找）

---

## Phase 4: User Story 2 - 沙箱执行一个外部命令工具 (Priority: P2)

**Goal**: SandboxedTool 正常执行返回标准输出；非零退出码识别为业务失败；
启动失败识别为基础设施失败

**Independent Test**: 用 echo_args.py（正常）与 exit_nonzero.py（非零退出码）
驱动 SandboxedTool.invoke()，验证参数传递与两类结果的区分

- [X] T012 [US2] 实现沙箱执行编排 src/kernel/tool/sandbox.py：SandboxedTool
      类——__init__(name, description, command, limits)；invoke(arguments,
      tenant_id) 的核心路径：建临时工作目录（FR-008）→ 启动运行器子进程
      （command 前缀为 `sys.executable -m kernel.tool.sandbox_runner`）→
      写入 json.dumps(arguments) 到 stdin 并关闭 → 等待进程结束 → 读取
      stdout（暂不含截断，T015 补全）→ 退出码 0 返回内容、非 0 抛
      SandboxToolExecutionError(exit_code, stderr_snippet) → 清理工作目录
      （状态机见 data-model.md，暂不含超时/资源判定，US3 补全）
- [X] T013 [US2] 在 src/kernel/tool/sandbox.py 补全启动失败处理：判定子进程
      returncode == 127（T007 运行器约定的保留退出码）时转换为
      SandboxStartupError(detail)（FR-010 的"启动失败"类型；不尝试捕获
      跨进程的 Python 异常，识别机制见 data-model.md）
- [X] T014 [US2] 包级导出 src/kernel/tool/__init__.py 追加：按
      contracts/tool-registry-sandbox-api.md 导出 ToolRegistry、
      SandboxedTool、SandboxLimits、异常层级（保留 001 已有的 Tool
      Protocol 与 EchoTool 导出不变）
- [X] T015 [P] [US2] 正常执行与参数传递单元测试
      tests/unit/tool/test_sandbox_success.py：调用 echo_args.py 包装的
      SandboxedTool，验证返回内容包含传入的 arguments（验收场景 US2-1/3）
- [X] T016 [P] [US2] 业务失败与启动失败单元测试
      tests/unit/tool/test_sandbox_business_failure.py：调用
      exit_nonzero.py 包装的 SandboxedTool 抛 SandboxToolExecutionError
      且携带正确的 exit_code（验收场景 US2-2）；command 指向不存在的
      可执行文件时抛 SandboxStartupError（Edge Case）

**Checkpoint**: US1+US2 测试全绿——沙箱执行的成功/业务失败路径完整

---

## Phase 5: User Story 3 - 沙箱对超时与资源超限的强制终止 (Priority: P3)

**Goal**: 超时在所有平台强制生效；CPU/内存超限仅 POSIX 硬性生效

**Independent Test**: 用 sleep_forever.py 驱动超时场景（所有平台）；
用 grow_memory.py 驱动资源超限场景（仅 POSIX，Windows 跳过）

- [X] T017 [US3] 在 src/kernel/tool/sandbox.py 补全超时判定：用
      asyncio.wait_for 包裹子进程等待，超时后终止子进程（跨平台的
      进程终止方式）并抛 SandboxTimeoutError(timeout_seconds)（FR-006，
      所有平台生效）
- [X] T018 [US3] 在 src/kernel/tool/sandbox.py 补全资源超限识别（仅
      POSIX）：判定 `process.returncode < 0`（POSIX 信号终止，asyncio
      report 为负的信号编号，如 -9=SIGKILL、-24=SIGXCPU）时映射为
      SandboxResourceExceededError(resource_name, limit)——SIGKILL 关联
      max_memory_bytes（RLIMIT_AS），SIGXCPU 关联 max_cpu_seconds
      （RLIMIT_CPU）；与 returncode > 0 的普通业务失败、returncode == 127
      的启动失败均需可区分（FR-007，data-model.md 状态流转，research.md R2/R5）
- [X] T019 [P] [US3] 超时单元测试 tests/unit/tool/test_sandbox_timeout.py：
      sleep_forever.py 配合短超时 SandboxLimits，验证在超时的 1.5 倍
      时间内被强制终止并抛 SandboxTimeoutError（验收场景 US3-1，SC-003，
      本测试在所有平台运行）
- [X] T020 [P] [US3] 资源超限单元测试
      tests/unit/tool/test_sandbox_resource_limit.py：grow_memory.py
      配合较小的 max_memory_bytes，验证抛 SandboxResourceExceededError
      （验收场景 US3-2）；用 `@pytest.mark.skipif(sys.platform == "win32",
      reason="资源限制仅 POSIX 硬性生效，见 research.md R2")` 标注
      （不是静默跳过）
- [X] T021 [P] [US3] 安全默认值单元测试 tests/unit/tool/test_sandbox_timeout.py
      （同文件追加）：未显式配置 SandboxLimits 时采用安全默认值，
      任何限额字段均不允许为"无限制"（验收场景 US3-3，复用 T009 的
      SandboxLimits 校验，此处从 SandboxedTool 构造视角验证）

**Checkpoint**: US1-US3 测试全绿——沙箱的时间与资源边界保护完整

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 输出截断、遥测、演示脚本、文档收尾与最终验证

- [X] T022 [P] 在 src/kernel/tool/sandbox.py 补全输出截断：读取 stdout 时
      按 SandboxLimits.max_output_bytes 截断，超出部分在返回内容末尾追加
      明确的截断标记文本（research.md R4，Edge Case）
- [X] T023 [P] 实现操作遥测 src/kernel/tool/telemetry.py：tool_invoke_span
      (tenant_id, tool_name) 上下文管理器，span name="tool.invoke"，
      复用 kernel.provider 的 tracer（research.md R7），可后补 result_type/
      duration_seconds 属性，遥测异常 try/except 不影响调用
- [X] T024 在 src/kernel/tool/sandbox.py 集成遥测：invoke() 全程经
      tool_invoke_span 包裹，各失败类型对应设置 result_type
      （success/timeout/resource_exceeded/startup_failed/nonzero_exit）
      （FR-011，data-model.md span 契约）
- [X] T025 [P] 输出截断与遥测单元测试 tests/unit/tool/test_sandbox_telemetry.py：
      超长输出被截断且含截断标记；span 属性含 tenant_id/tool_name/
      result_type/duration_seconds，各失败类型的 result_type 可区分
      （SC-004）；注入抛异常的 span 处理不影响调用结果
- [X] T026 [P] 并发调用单元测试 tests/unit/tool/test_sandbox_concurrency.py：
      同一 SandboxedTool 实例并发发起多次 invoke()（echo_args.py，各次传入
      不同 arguments），验证各自返回内容与传入参数一一对应、互不串扰
      （各自独立的临时工作目录与子进程，spec Edge Cases 第 4 条）
- [X] T027 [P] 创建演示脚本 examples/demo_tool_sandbox.py：注册可信工具与
      沙箱工具、演示重名拒绝、正常执行、超时、非零退出码四个场景并打印
      span（quickstart.md 第 2 节的预期输出）
- [X] T028 按 quickstart.md 全流程验证：pytest 全绿（含 Windows 上资源
      超限测试的预期 SKIPPED，SC-001）→ demo 输出符合预期
      （SC-002/003/004）→ 计时确认 15 分钟内完成，修复发现的问题
- [X] T029 更新 README.md roadmap：005 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：仅依赖 Phase 2 的 T006（异常层级，重名注册需要
  InvalidRequestError），与 US2/US3 无交叉，可完全独立完成
- **US2 → US3**：均在 `sandbox.py` 上演进，US2 建立核心执行路径
  （成功/业务失败/启动失败），US3 补全超时与资源限额判定
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 1 内：T002/T003/T004/T005 全部并行（互不依赖的独立脚本文件）
- Phase 2 内：T007/T008/T009 并行（T006 先行）
- US1 与 US2/US3：ToolRegistry（US1）不依赖 SandboxedTool（US2/US3）的
  具体实现，可与 US2 并行开工
- US2 内：T015、T016 同属并行准备（不同测试文件）
- US3 内：T019、T020、T021 同属并行准备（T021 与 T019 同文件但断言独立）
- Phase 6：T022/T023/T026/T027 可并行，T024 依赖 T023，T025 依赖 T024，
  T028 依赖 T027

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T011）：工具的统一注册与查找即可演示
核心价值，且完全不需要沙箱执行验证通过。随后 US2（沙箱成功/业务失败路径）
→ US3（超时/资源边界）递增交付，最后 Polish 补齐输出截断、遥测与演示脚本。
每个 Checkpoint 处 `pytest` 必须全绿（Windows 上的预期 SKIPPED 除外）再前进。
