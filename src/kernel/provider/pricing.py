"""成本计算与输入 token 粗估（research.md R8/R9）。"""

from kernel.provider.models import LLMRequest, PriceTable, TokenUsage


def estimate_input_tokens(request: LLMRequest) -> int:
    """输入 token 粗估：总字符数 / 4。

    已知偏差：对中文等非拉丁文本严重低估 token 数（中文约 1-2 字符/token），
    导致高估剩余输出预算——由响应侧的实际 usage 校验兜底（双侧执行），
    此处不引入 tokenizer 依赖（宪法原则 II）。
    """
    total_chars = sum(len(m.content) for m in request.messages)
    return max(1, total_chars // 4)


def calculate_cost(model: str, usage: TokenUsage, price_table: PriceTable) -> float:
    price = price_table.price_for(model)
    return (
        usage.input_tokens / 1000 * price.input_per_1k_usd
        + usage.output_tokens / 1000 * price.output_per_1k_usd
    )
