class ServiceNowError(Exception):
    """Base class. `retryable` tells callers whether trying again can help."""

    retryable: bool = False

    def __init__(self, message: str, *, status_code: int | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.message} | {self.detail}" if self.detail else self.message


class ServiceNowValidationError(ServiceNowError):
    """Bad input, caught before or by the API (HTTP 400)."""


class ServiceNowAuthError(ServiceNowError):
    """Wrong credentials (HTTP 401)."""


class ServiceNowForbiddenError(ServiceNowError):
    """Role or ACL blocks the operation (HTTP 403)."""


class ServiceNowDataPolicyError(ServiceNowError):
    """A data policy rejected the change, e.g. a mandatory field (HTTP 403)."""


class ServiceNowNotFoundError(ServiceNowError):
    """Record does not exist or is not visible (HTTP 404)."""


class ServiceNowRateLimitError(ServiceNowError):
    retryable = True


class ServiceNowUnavailableError(ServiceNowError):
    """Timeout, connection failure, 5xx, or the instance is hibernating."""

    retryable = True
