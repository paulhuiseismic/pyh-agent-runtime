"""ReactEngine：思考-行动-观察循环编排（状态机见 specs/002 data-model.md）。"""

from kernel.provider import LLMProvider, LLMRequest
from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import Limits
from kernel.react.models import Observation, StepBudgetExceededError
from kernel.react.prompting import build_thought_messages, parse_thought
from kernel.react.telemetry import react_step_span
from kernel.tool import Tool


class ReactEngine:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: dict[str, Tool],
        model: str,
        max_step_limits: Limits | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._model = model
        self._max_step_limits = max_step_limits

    async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str:
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps <= 0:
            raise InvalidRequestError(
                f"max_steps 必须为正整数（宪法原则 VI 禁止无界循环），收到: {max_steps!r}"
            )
        if not goal or not goal.strip():
            raise InvalidRequestError("goal 必填且不能为空")
        if not tenant_id or not tenant_id.strip():
            raise InvalidRequestError("tenant_id 必填且不能为空")

        tool_descriptions = {name: tool.description for name, tool in self._tools.items()}
        history: list[tuple[str, Observation]] = []

        for step_index in range(1, max_steps + 1):
            result = await self._run_one_step(
                step_index=step_index,
                is_last_step=(step_index == max_steps),
                goal=goal,
                tenant_id=tenant_id,
                tool_descriptions=tool_descriptions,
                history=history,
            )
            if isinstance(result, str):  # final_answer
                return result
            action_summary, observation = result
            history.append((action_summary, observation))

        raise AssertionError("unreachable")  # max_steps>=1 时循环必 return 或抛异常

    async def _run_one_step(
        self, *, step_index, is_last_step, goal, tenant_id, tool_descriptions, history
    ):
        # provider 调用必须发生在 react.step span 内部，使其 chat span 成为子 span
        # （research.md R5）；action/tool_name 属性在思考结果解析后补充设置；
        # 步数耗尽的异常也在 span 内抛出，使最后一步 span 标记 ERROR（data-model.md）。
        with react_step_span(step_index) as span_handle:
            messages = build_thought_messages(goal, tool_descriptions, history)
            request = LLMRequest(
                tenant_id=tenant_id,
                model=self._model,
                messages=messages,
                limits=self._max_step_limits,
            )
            response = await self._provider.complete(request)
            decision = parse_thought(response.content)

            if decision.action == "final_answer":
                span_handle.set_action("final_answer")
                return decision.content

            if decision.action == "call_tool":
                span_handle.set_action("call_tool", decision.tool)
                observation = await self._invoke_tool(decision.tool, decision.arguments, tenant_id)
                action_summary = f"call_tool: {decision.tool}"
            else:
                span_handle.set_action("malformed")
                observation = Observation(
                    success=False, content=f"思考结果格式非法: {decision.raw}"
                )
                action_summary = "malformed"

            if is_last_step:
                raise StepBudgetExceededError(
                    steps_executed=step_index, last_observation=observation.content
                )
            return action_summary, observation

    async def _invoke_tool(self, tool_name: str, arguments: dict, tenant_id: str) -> Observation:
        tool = self._tools.get(tool_name)
        if tool is None:
            return Observation(success=False, content=f"工具未注册: {tool_name!r}")
        try:
            result = await tool.invoke(arguments, tenant_id=tenant_id)
        except Exception as exc:
            return Observation(success=False, content=f"工具执行异常: {exc!r}")
        return Observation(success=True, content=result)
