"""ReAct 引擎实战 demo：查询天气并给出穿衣建议。

演示 001（provider）+ 002（react）组合解决一个真实目标：
ReactEngine 驱动真实 LiteLLM proxy 做推理，决定何时调用 WeatherTool
（查询 Open-Meteo 免费天气 API，无需 API key），再基于天气结果给出穿衣建议。

前置条件:
  1. 本地运行 LiteLLM proxy（见 examples/litellm-config.yaml 的启动命令），
     并设置 OPENAI_API_KEY（或改用你已有的其他模型/proxy 配置）。
  2. 网络可访问 open-meteo.com（免费、无需注册）。

环境变量:
  LITELLM_BASE_URL   默认 http://localhost:4000
  LITELLM_API_KEY    可选，proxy 侧的虚拟 key
  WEATHER_MODEL      默认 gpt-4o-mini（须与 litellm-config.yaml 中的 model_name 一致）

运行:
  python examples/demo_react_weather.py "北京"
"""

import asyncio
import os
import sys

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.provider import LLMProvider, ModelPrice, PriceTable, ProviderError
from kernel.react import ReactEngine, StepBudgetExceededError

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT_SECONDS = 10.0  # 宪法原则 IV：所有外部调用必须显式超时

# WMO 天气代码的简化说明（仅覆盖常见取值，供人类可读展示）
_WEATHER_CODE_DESC = {
    0: "晴朗", 1: "大致晴朗", 2: "局部多云", 3: "阴天",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "中等阵雨", 82: "强阵雨",
    95: "雷暴",
}


class WeatherTool:
    """查询指定城市的当前天气（Open-Meteo 免费 API，无需 key）。"""

    name = "get_weather"
    description = (
        '查询指定城市的当前天气（温度、天气状况、风速）。'
        '参数: {"city": "<城市名，如 Beijing 或 北京>"}'
    )

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        city = arguments.get("city")
        if not city:
            raise ValueError("缺少必需参数 city")

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            geo_resp = await client.get(GEOCODING_URL, params={"name": city, "count": 1})
            geo_resp.raise_for_status()
            geo_results = geo_resp.json().get("results")
            if not geo_results:
                return f"未找到城市 {city!r} 的地理位置信息"

            location = geo_results[0]
            lat, lon = location["latitude"], location["longitude"]
            resolved_name = location.get("name", city)

            forecast_resp = await client.get(
                FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                },
            )
            forecast_resp.raise_for_status()
            current = forecast_resp.json()["current"]

        temp = current["temperature_2m"]
        wind = current["wind_speed_10m"]
        weather_desc = _WEATHER_CODE_DESC.get(current["weather_code"], "未知天气状况")
        return (
            f"{resolved_name}当前天气: {weather_desc}, 气温 {temp}°C, "
            f"风速 {wind} km/h"
        )


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


async def main() -> None:
    city = sys.argv[1] if len(sys.argv) > 1 else "北京"
    base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
    api_key = os.environ.get("LITELLM_API_KEY")
    model = os.environ.get("WEATHER_MODEL", "gpt-4o-mini")

    setup_console_tracing()

    provider = LLMProvider(
        base_url=base_url,
        api_key=api_key,
        # 演示用单价（近似 gpt-4o-mini 官方定价），请按实际模型调整
        price_table=PriceTable(
            prices={model: ModelPrice(input_per_1k_usd=0.00015, output_per_1k_usd=0.0006)}
        ),
    )
    engine = ReactEngine(provider=provider, tools={"get_weather": WeatherTool()}, model=model)

    goal = f"查询{city}当前的天气，并根据天气给出具体的穿衣搭配建议"
    print(f"目标: {goal}\n")

    try:
        answer = await engine.run(goal, tenant_id="tenant-weather-demo", max_steps=5)
        print(f"\n=== 最终建议 ===\n{answer}")
    except StepBudgetExceededError as exc:
        print(f"\n未在步数上限内得出结论: {exc}")
    except ProviderError as exc:
        print(f"\nLLM 调用失败（{type(exc).__name__}）: {exc}")
        print(f"请确认 LiteLLM proxy 运行于 {base_url} 且已配置模型 {model!r}")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
