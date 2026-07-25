"""react 模块接口骨架（完整实现属 feature 002）。

ReAct 循环必须有最大步数限制（宪法原则 VI）——max_steps 为必填参数。
"""

from typing import Protocol, runtime_checkable

from kernel.provider.errors import InvalidRequestError


@runtime_checkable
class ReactLoop(Protocol):
    async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str: ...


class SingleShotReactLoop:
    """占位实现：不做真实推理，仅锁定接口签名与 max_steps 约束。"""

    async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str:
        if max_steps <= 0:
            raise InvalidRequestError(
                f"max_steps 必须为正整数（宪法原则 VI 禁止无界循环），收到: {max_steps}"
            )
        if not tenant_id or not tenant_id.strip():
            raise InvalidRequestError("tenant_id 必填且不能为空")
        return f"[placeholder] goal={goal!r} 未执行（react 完整实现属 feature 002）"


__all__ = ["ReactLoop", "SingleShotReactLoop"]
