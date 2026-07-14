from __future__ import annotations

import os
import threading
from typing import Optional

from .cache_engine import request_background_refresh

_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_THREAD: Optional[threading.Thread] = None
_STOP_EVENT = threading.Event()
_INTERVAL_SECONDS = max(60, int(os.getenv("BBLOTTO_AI_REFRESH_INTERVAL", "300") or 300))


def _loop() -> None:
    # 시작 직후에는 기존 캐시를 사용하고, 첫 주기부터 새 회차를 확인합니다.
    while not _STOP_EVENT.wait(_INTERVAL_SECONDS):
        request_background_refresh(force_check=True)


def ensure_scheduler_started() -> bool:
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return False
        _STOP_EVENT.clear()
        _SCHEDULER_THREAD = threading.Thread(
            target=_loop,
            name="bblotto-ai-auto-refresh",
            daemon=True,
        )
        _SCHEDULER_THREAD.start()
        return True


def stop_scheduler() -> None:
    _STOP_EVENT.set()
