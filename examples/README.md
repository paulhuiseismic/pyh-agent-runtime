# Examples

内核能力的可运行演示。除 `demo_react_weather.py` 外均为 stub 演示，
无需网络、无需真实模型密钥（见各 feature 的 `quickstart.md`）。

| 脚本 | 依赖 | 演示内容 |
|------|------|----------|
| `demo_stub.py` | 无（httpx.MockTransport） | provider：成功调用 / 超时 / 成本超限 |
| `demo_proxy.py` | 真实 LiteLLM proxy | provider 对接真实模型的最小示例 |
| `demo_react_stub.py` | 无（httpx.MockTransport） | react：直接回答 / 工具调用 / 步数耗尽 |
| `demo_react_weather.py` | 真实 LiteLLM proxy + 真实 Open-Meteo API | react + provider 组合：查天气给穿衣建议 |

## demo_proxy.py：provider 对接真实模型

**目标**：验证 001 的 `LLMProvider` 能通过真实 LiteLLM proxy 完成一次调用
（非流式，含超时/token/成本上限、GenAI span）。

### 前置条件

- 一个已在运行的 LiteLLM proxy（见下方 demo_react_weather.py 的"配置 LiteLLM"
  与"启动 LiteLLM proxy"两节，两个 demo 共用同一个 proxy）

### 运行

```powershell
.venv\Scripts\python examples\demo_proxy.py azure-gpt4o-mini
```

- 参数为模型名，须与 `litellm-config.yaml` 里的 `model_name` 一致
- 默认 `LITELLM_BASE_URL=http://localhost:4000`；proxy 未启用
  `master_key` 鉴权时不需要设置 `LITELLM_API_KEY`

### 预期输出

模型名回显、一句自我介绍、token 用量、按脚本内单价（`0.15`/`0.6` 每千
token，通用估值非 Azure 实际单价，仅影响 `cost` 展示准确性）算出的成本，
以及一条控制台 GenAI span（含 `tenant_id=tenant-demo`）。

**已验证**：2026-07-26 使用 Azure OpenAI（`azure-gpt4o-mini` 部署）运行通过。

---

## demo_react_weather.py：查天气给穿衣建议

**目标**：ReactEngine 用真实 LLM 推理，决定何时调用 `WeatherTool`
（查询 Open-Meteo 免费天气 API，无需 key），再基于天气结果给出穿衣建议。

### 前置条件

- Docker（跑 LiteLLM proxy）
- 一个可用的模型 key（Azure OpenAI / OpenAI 均可）
- 网络可访问 `open-meteo.com`（免费、无需注册）

### 1. 配置 LiteLLM

编辑 [litellm-config.yaml](litellm-config.yaml)：

- **Azure OpenAI**：把 `model: azure/<your-deployment-name>` 中的
  `<your-deployment-name>` 换成 Azure 门户里的 **Deployment name**
  （不是模型名如 `gpt-4o`，是你自定义的部署名）。
- **纯 OpenAI**：改用文件底部注释掉的 `gpt-4o-mini` 配置块替换 `model_list`。

`model_name`（对外别名）与 `demo_react_weather.py` 的 `WEATHER_MODEL`
环境变量必须一致，成本单价表才能对上号。

### 2. 启动 LiteLLM proxy

PowerShell（Windows）：

```powershell
# Docker Desktop 若处于 paused 状态，先从 Whale 菜单 Unpause

docker run -p 4000:4000 `
  -v "${PWD}/examples/litellm-config.yaml:/app/config.yaml" `
  -e AZURE_API_KEY=<你的key> `
  -e AZURE_API_BASE=<你的endpoint> `
  -e AZURE_API_VERSION=<你的api version> `
  ghcr.io/berriai/litellm:main-stable --config /app/config.yaml
```

纯 OpenAI 只需 `-e OPENAI_API_KEY=<你的key>`，不需要 `AZURE_*` 三个变量。

密钥只留在本地终端命令里，不要贴进对话或提交进 git。

### 3. 运行 demo

另开一个终端：

```powershell
$env:WEATHER_MODEL = "azure-gpt4o-mini"   # 需与 litellm-config.yaml 的 model_name 一致
.venv\Scripts\python examples\demo_react_weather.py "北京"
```

参数为城市名，缺省为"北京"。

### 预期输出

- 每一步的 `react.step` span（控制台 JSON），其下挂载该步内的 `chat` 子 span
- 第一步：ReactEngine 决定调用 `get_weather`
- 第二步：基于天气观察结果给出最终的穿衣建议

### 常见问题排查

| 报错 | 可能原因 |
|------|----------|
| 401 | `AZURE_API_KEY` 错误，或 key 与 `AZURE_API_BASE` 所属资源不匹配 |
| 404 | Deployment name 拼写错误，或 `AZURE_API_BASE` 少了/多了路径 |
| `CallTimeoutError` | proxy 未启动、端口未映射，或 `AZURE_API_VERSION` 版本过旧不被支持 |
| 天气查询失败 | 城市名无法被 Open-Meteo 地理编码识别，换更常见的英文/中文城市名重试 |

### 切换到其他模型

若部署的不是 `gpt-4o-mini`，把 `demo_react_weather.py` 中的
`ModelPrice(input_per_1k_usd=..., output_per_1k_usd=...)` 换成对应模型的
实际单价（每千 token 美元），否则仅影响 `cost_usd` 的展示准确性，不影响功能。
