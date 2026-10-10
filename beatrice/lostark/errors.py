"""Public errors contain neither credentials nor raw server responses."""


class LostArkError(Exception):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


class LostArkAuthError(LostArkError):
    """Missing/unreadable saved key, or HTTP 401/403."""


class LostArkRateLimitError(LostArkError):
    def __init__(self, *, retry_after=None):
        super().__init__('로스트아크 API 호출 제한에 도달했습니다.', status=429)
        self.retry_after = retry_after


class LostArkNotFoundError(LostArkError):
    """HTTP 404. Successful JSON null responses remain None."""


class LostArkNetworkError(LostArkError):
    """Connection or timeout failure."""


class LostArkResponseError(LostArkError):
    """Other HTTP errors or an invalid JSON response."""
