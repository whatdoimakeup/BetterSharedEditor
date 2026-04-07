"""
Custom Django middleware for request timing.
"""

import logging
import time
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("core.request_timing")


class RequestTimingMiddleware:
    """Log request duration and expose it as a response header."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started_at = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - started_at) * 1000

        response["X-Request-Time-ms"] = f"{duration_ms:.2f}"
        logger.info(
            "%s %s -> %s in %.2f ms",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
        )

        return response
