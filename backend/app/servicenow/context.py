from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("nexusdesk_request_id", default=None)


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    """Set by the graph for each workflow run so a retried node cannot create a second ticket."""
    token = request_id_var.set(request_id)
    try:
        yield
    finally:
        request_id_var.reset(token)
