class AuthenticationError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"tenant authentication failed: {detail}")


class ConcurrencyLimitExceededError(Exception):
    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"concurrency limit exceeded (scope={scope})")


class RequestTimeoutError(Exception):
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"request processing timed out after {timeout_seconds}s")
