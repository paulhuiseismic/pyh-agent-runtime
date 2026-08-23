"""消息网关：与 app.py（REST）/cli.py（CLI）并列的第三个平台入口。

契约见 specs/009-message-channels/contracts/message-gateway-api.md。
不复用 007 的 ConcurrencyScheduler（同 008 的 CLI 一样，此处也没有
"单进程内并发调用同一网关"的真实场景）；异步处理用标准库
`asyncio.create_task`，不引入消息队列（research.md R1）。
"""

import asyncio
import logging

import httpx

from platform_service.config import ChannelConfig, PlatformConfig
from platform_service.errors import ChannelNotFoundError, QuotaExceededError
from platform_service.models import AgentRunRequest, InboundAcceptResult, InboundMessage
from platform_service.telemetry import platform_request_span

logger = logging.getLogger(__name__)

_CALLBACK_RETRY_DELAY_SECONDS = 0.1


class ProcessedMessageRegistry:
    """按 (channel_id, external_message_id) 去重（进程内存，
    research.md R4）。"""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def check_and_mark(self, channel_id: str, external_message_id: str) -> bool:
        key = (channel_id, external_message_id)
        async with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True


async def send_callback_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    *,
    timeout: float,
    max_retries: int,
) -> None:
    """对出站回调做固定间隔、有限次数的重试；全部失败仅记录日志，
    不向调用方抛出（research.md R3，FR-008）。"""
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return
        except Exception:
            if attempt < max_retries:
                await asyncio.sleep(_CALLBACK_RETRY_DELAY_SECONDS)
            else:
                logger.warning(
                    "message gateway callback delivery failed after %d attempts "
                    "(url=%s)",
                    max_retries,
                    url,
                    exc_info=True,
                )


class MessageGateway:
    def __init__(
        self,
        *,
        agent_service,
        channels: list[ChannelConfig],
        callback_client: httpx.AsyncClient,
        request_timeout_seconds: float,
        callback_timeout_seconds: float,
        callback_max_retries: int,
    ) -> None:
        self._agent_service = agent_service
        self._channels_by_id = {c.channel_id: c for c in channels}
        self._callback_client = callback_client
        self._request_timeout_seconds = request_timeout_seconds
        self._callback_timeout_seconds = callback_timeout_seconds
        self._callback_max_retries = callback_max_retries
        self._registry = ProcessedMessageRegistry()
        self._background_tasks: set[asyncio.Task] = set()

    def _resolve_channel(self, channel_id: str) -> ChannelConfig:
        channel = self._channels_by_id.get(channel_id)
        if channel is None:
            raise ChannelNotFoundError(channel_id)
        return channel

    async def handle_inbound(self, message: InboundMessage) -> InboundAcceptResult:
        channel = self._resolve_channel(message.channel_id)

        is_new = await self._registry.check_and_mark(
            message.channel_id, message.external_message_id
        )
        if not is_new:
            return InboundAcceptResult(accepted=True, duplicate=True)

        task = asyncio.create_task(self._process_and_callback(message, channel))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return InboundAcceptResult(accepted=True, duplicate=False)

    async def _process_and_callback(
        self, message: InboundMessage, channel: ChannelConfig
    ) -> None:
        with platform_request_span(
            tenant_id=channel.tenant_id, session_id=message.conversation_id
        ) as span:
            payload = {
                "external_message_id": message.external_message_id,
                "conversation_id": message.conversation_id,
                "status": "success",
                "answer": None,
                "error": None,
            }
            try:
                result = await asyncio.wait_for(
                    self._agent_service.handle(
                        AgentRunRequest(
                            goal=message.text, session_id=message.conversation_id
                        ),
                        tenant_id=channel.tenant_id,
                        source="message_gateway",
                    ),
                    timeout=self._request_timeout_seconds,
                )
            except asyncio.TimeoutError:
                span.set_result("timeout")
                payload["status"] = "timeout"
                payload["error"] = (
                    f"request processing timed out after "
                    f"{self._request_timeout_seconds}s"
                )
            except QuotaExceededError as exc:
                span.set_result("quota_exceeded")
                payload["status"] = "quota_exceeded"
                payload["error"] = str(exc)
            except Exception as exc:
                span.set_result("kernel_error")
                payload["status"] = "kernel_error"
                payload["error"] = str(exc)
            else:
                span.set_result("success")
                payload["answer"] = result.answer

        await send_callback_with_retry(
            self._callback_client,
            channel.callback_url,
            payload,
            timeout=self._callback_timeout_seconds,
            max_retries=self._callback_max_retries,
        )

    async def wait_for_background_tasks(self) -> None:
        """测试专用：确定性等待所有已调度的后台任务完成（research.md R2）。"""
        tasks = list(self._background_tasks)
        if tasks:
            await asyncio.gather(*tasks)


async def build_message_gateway(
    config: PlatformConfig,
    *,
    agent_service,
    callback_client: httpx.AsyncClient | None = None,
) -> MessageGateway:
    if callback_client is None:
        callback_client = httpx.AsyncClient(timeout=config.callback_timeout_seconds)

    return MessageGateway(
        agent_service=agent_service,
        channels=config.channels,
        callback_client=callback_client,
        request_timeout_seconds=config.request_timeout_seconds,
        callback_timeout_seconds=config.callback_timeout_seconds,
        callback_max_retries=config.callback_max_retries,
    )
