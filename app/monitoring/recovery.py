"""Safe, opt-in service recovery actions.

Recovery handlers are injected by trusted application code. Configuration selects
an allowlisted action name but cannot provide a shell command or executable path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import logging
from time import monotonic
from typing import Callable, Any

from app.monitoring.service_checker import ServiceConfig, ServiceHealth


RecoveryHandler = Callable[[], bool]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryResult:
    service: str
    action: str
    status: str
    attempt: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecoveryManager:
    """Execute only injected recovery handlers with retry and cooldown guards."""

    def __init__(
        self,
        handlers: dict[str, RecoveryHandler] | None = None,
        service_handlers: dict[tuple[str, str], RecoveryHandler] | None = None,
        dry_run: bool = True,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.handlers = dict(handlers or {})
        self.service_handlers = dict(service_handlers or {})
        self.dry_run = dry_run
        self._clock = clock
        self._attempts: dict[str, tuple[int, float]] = {}

    def recover(self, service: ServiceConfig, health: ServiceHealth) -> RecoveryResult:
        """Attempt recovery for one DOWN service without propagating errors."""
        policy = service.recovery
        if health.status != "DOWN":
            return self._result(service, "SKIPPED", 0, "service is not down")
        if not policy.enabled:
            return self._result(service, "DISABLED", 0, "recovery is not enabled")
        if policy.action == "none":
            return self._result(service, "DISABLED", 0, "no recovery action selected")

        now = self._clock()
        previous_attempts, last_attempt = self._attempts.get(service.name, (0, 0.0))
        if previous_attempts >= policy.max_attempts:
            return self._result(service, "RETRY_LIMIT", previous_attempts, "retry limit reached")
        if previous_attempts and now - last_attempt < policy.cooldown_seconds:
            return self._result(service, "COOLDOWN", previous_attempts, "cooldown is active")

        attempt = previous_attempts + 1
        self._attempts[service.name] = (attempt, now)
        if self.dry_run:
            return self._result(service, "DRY_RUN", attempt, "recovery action was not executed")

        handler = self.service_handlers.get((service.name, policy.action))
        if handler is None:
            handler = self.handlers.get(policy.action)
        if handler is None:
            return self._result(service, "FAILED", attempt, "recovery action is not allowlisted")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            succeeded = executor.submit(handler).result(timeout=policy.timeout_seconds)
        except FutureTimeout:
            executor.shutdown(wait=False, cancel_futures=True)
            return self._result(service, "FAILED", attempt, "recovery action timed out")
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            return self._result(service, "FAILED", attempt, f"recovery action failed: {exc}")
        executor.shutdown(wait=True)
        if succeeded:
            self._attempts.pop(service.name, None)
            return self._result(service, "SUCCEEDED", attempt, "recovery action completed")
        return self._result(service, "FAILED", attempt, "recovery action reported failure")

    @staticmethod
    def _result(service: ServiceConfig, status: str, attempt: int, message: str) -> RecoveryResult:
        result = RecoveryResult(service.name, service.recovery.action, status, attempt, message)
        logger.info(
            "recovery service=%s action=%s status=%s attempt=%s message=%s",
            result.service,
            result.action,
            result.status,
            result.attempt,
            result.message,
        )
        return result