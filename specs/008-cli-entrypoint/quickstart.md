# Quickstart: CLI 入口（复用平台服务层）

## 前置条件

- 已完成 007（`platform_service` 包已存在）。
- 一份平台配置文件（结构同
  [examples/platform_config.example.json](../../examples/platform_config.example.json)），
  指向一个可达的 LiteLLM proxy（或本地测试可用 stub，见下方“无网络验证”）。

## 1. 安装（开发环境）

```powershell
.venv\Scripts\pip install -e .
```

安装后 `pyh-agent` 控制台命令可用（`pyproject.toml` `[project.scripts]`
声明），等价于 `python -m platform_service.cli`。

## 2. 配置并运行（需要真实 LiteLLM proxy）

```powershell
$env:PLATFORM_SERVICE_API_KEY = "demo-key"
$env:PLATFORM_SERVICE_CONFIG = "examples/platform_config.example.json"
pyh-agent "1+1等于几？"
```

**预期输出**：stdout 打印最终答案文本，进程退出码为 `0`
（`echo $LASTEXITCODE` 验证）。

## 3. 会话延续

```powershell
pyh-agent "我叫小明" --session-id demo-session-1
pyh-agent "我叫什么名字？" --session-id demo-session-1
```

**预期输出**：第二次调用的回答体现出对"小明"这一此前对话内容的记忆
（复用 003 会话记忆，两次调用是两个独立进程）。

## 4. 失败场景验证

| 场景 | 命令 | 预期退出码 |
|------|------|-----------|
| 未设置 API Key | `Remove-Item Env:PLATFORM_SERVICE_API_KEY; pyh-agent "test"` | `1`（`EXIT_MISSING_API_KEY`） |
| API Key 不匹配 | `$env:PLATFORM_SERVICE_API_KEY="wrong"; pyh-agent "test"` | `2`（`EXIT_AUTH_FAILED`） |
| 配置文件缺失 | `pyh-agent "test" --config not-exist.json` | `3`（`EXIT_CONFIG_INVALID`） |
| 问题为空 | `pyh-agent ""` | `4`（`EXIT_VALIDATION_FAILED`） |

具体退出码含义见 [contracts/cli-contract.md](contracts/cli-contract.md)。

## 5. 无网络验证（stub provider，供自动化测试/CI 使用）

单元测试与 `examples/demo_cli.py` 均通过向 `cli.run()` 注入一个用
`httpx.MockTransport` 构造的 stub `AgentService`（复用
`tests/unit/platform_service/conftest.py` 已有 fixture），验证成功/
各类失败退出码与 stdout/stderr 内容，无需真实网络或真实模型服务：

```powershell
.venv\Scripts\python examples\demo_cli.py
.venv\Scripts\python -m pytest tests/unit/platform_service/test_cli.py -v
```

**预期输出**：demo 脚本依次打印四种场景（成功/缺少 API Key/身份识别
失败/内核失败）的退出码与输出内容；pytest 全绿。

## 6. 打包链路冒烟验证

```powershell
.venv\Scripts\python -m pytest tests/unit/platform_service/test_cli.py -k smoke -v
```

**预期输出**：验证 `pyh-agent` console script（或
`python -m platform_service.cli`）确实可以作为独立子进程被调用并正确
退出，覆盖单元测试无法验证的打包声明本身。
