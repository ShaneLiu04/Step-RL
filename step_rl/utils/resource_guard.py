"""Resource guard for timeout and memory protection."""

import asyncio
import signal
from typing import Any, Callable
from functools import wraps


def timeout(seconds: int):
    """Decorator for timeout protection.

    For async functions, wraps the call in ``asyncio.wait_for``.
    For sync functions, uses ``SIGALRM`` (Unix only).
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            # SIGALRM is not available on Windows; gracefully degrade
            if not hasattr(signal, "SIGALRM"):
                return func(*args, **kwargs)

            def handler(signum, frame):
                raise TimeoutError(f"Function timed out after {seconds} seconds")

            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            try:
                return func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
