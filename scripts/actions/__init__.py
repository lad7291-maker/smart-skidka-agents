# actions package
"""
Действия агентов над внешними системами.

Модули:
    - file_utils: безопасные операции с файлами (с бэкапом)
    - site_actions: операции над сайтом (meta, категории, товары)
    - telegram_actions: публикация в Telegram

Утилиты:
    - with_retry: декоратор для повторных попыток при ошибках
"""

import functools
import asyncio
import time
from typing import Callable, Any, Optional


def with_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], Any]] = None,
):
    """
    Декоратор для повторных попыток выполнения функции.

    Args:
        max_retries: Максимальное количество попыток
        delay: Начальная задержка между попытками (секунды)
        backoff: Множитель экспоненциального backoff
        exceptions: Кортеж исключений, при которых делается retry
        on_retry: Колбэк (exception, attempt) при каждой retry-попытке

    Example:
        @with_retry(max_retries=3, delay=1.0)
        def fragile_operation():
            ...

        @with_retry(max_retries=3, delay=1.0)
        async def async_fragile_operation():
            ...
    """
    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception = None
                current_delay = delay

                for attempt in range(1, max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt >= max_retries:
                            raise last_exception

                        if on_retry:
                            on_retry(e, attempt)

                        await asyncio.sleep(current_delay)
                        current_delay *= backoff

                raise last_exception

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_exception = None
                current_delay = delay

                for attempt in range(1, max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt >= max_retries:
                            raise last_exception

                        if on_retry:
                            on_retry(e, attempt)

                        time.sleep(current_delay)
                        current_delay *= backoff

                raise last_exception

            return sync_wrapper

    return decorator
