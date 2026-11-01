"""简单重试装饰器，用于应对免费数据源的限流与瞬时网络错误。"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T")


def retry(
    exceptions: tuple[type[Exception], ...] = (Exception,),
    tries: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    logger: logging.Logger | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避重试。最后一次失败时原样抛出异常。"""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:  # noqa: ANN002, ANN003
            wait = delay
            for attempt in range(1, tries + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    if attempt == tries:
                        raise
                    if logger is not None:
                        logger.warning(
                            "%s 第 %d/%d 次失败（%s），%.1fs 后重试",
                            getattr(fn, "__name__", "call"),
                            attempt,
                            tries,
                            exc,
                            wait,
                        )
                    time.sleep(wait)
                    wait *= backoff
            raise RuntimeError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
