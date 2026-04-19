from __future__ import annotations

import time
from collections.abc import Callable

from .core.models import ReceiveConfig, ReceiveResult
from .core.service import MailAtlas


def receive_watch(
    atlas: MailAtlas,
    config: ReceiveConfig,
    *,
    interval_seconds: int = 60,
    stop_after: int | None = None,
    on_result: Callable[[ReceiveResult], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[ReceiveResult]:
    if interval_seconds < 1:
        raise ValueError("Receive watch interval must be a positive integer.")
    if stop_after is not None and stop_after < 1:
        raise ValueError("Receive watch max runs must be a positive integer.")

    results: list[ReceiveResult] = []
    run_count = 0

    while stop_after is None or run_count < stop_after:
        result = atlas.receive(config)
        results.append(result)
        run_count += 1
        if on_result:
            on_result(result)
        if stop_after is not None and run_count >= stop_after:
            break

        delay = interval_seconds
        if result.status in {"error", "not_configured", "cursor_reset_required"}:
            delay = min(interval_seconds * 2, 300)
        try:
            sleep(delay)
        except KeyboardInterrupt:
            break

    return results
