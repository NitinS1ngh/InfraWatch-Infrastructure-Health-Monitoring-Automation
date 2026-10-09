"""Coordinate system metrics, service checks, and log summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.log_parser.log_parser import LogParser, LogSummary
from app.monitoring.service_checker import ServiceChecker, ServiceHealth
from app.monitoring.system_metrics import SystemMetrics, SystemMetricsCollector
from app.monitoring.recovery import RecoveryManager


@dataclass(frozen=True)
class HealthThresholds:
    """Configurable conditions that turn a complete report into DEGRADED."""

    max_error_logs: int = 0
    max_critical_logs: int = 0


class HealthMonitor:
    """Create a unified health report without requiring a web server."""

    def __init__(
        self,
        system_collector: SystemMetricsCollector,
        service_checker: ServiceChecker,
        log_parser: LogParser,
        thresholds: HealthThresholds | None = None,
        recovery_manager: RecoveryManager | None = None,
    ) -> None:
        self.system_collector = system_collector
        self.service_checker = service_checker
        self.log_parser = log_parser
        self.thresholds = thresholds or HealthThresholds()
        self.recovery_manager = recovery_manager

    def collect(self) -> dict[str, Any]:
        """Collect all sources and return a report even when one source fails."""
        timestamp = _utc_now()
        monitoring_errors: list[str] = []
        system: SystemMetrics | None = None
        services: list[ServiceHealth] = []
        logs: LogSummary | None = None
        recovery_results: list[dict[str, Any]] = []

        try:
            system = self.system_collector.collect()
            monitoring_errors.extend(system.errors)
        except Exception as exc:
            monitoring_errors.append(f"system metrics collector failed: {exc}")

        try:
            services = self.service_checker.check_all()
            configured_services = getattr(self.service_checker, "services", ())
            if self.recovery_manager and len(configured_services) == len(services):
                for service_config, service_health in zip(configured_services, services):
                    try:
                        recovery_results.append(
                            self.recovery_manager.recover(service_config, service_health).to_dict()
                        )
                    except Exception as exc:
                        recovery_results.append(
                            {
                                "service": service_config.name,
                                "action": service_config.recovery.action,
                                "status": "FAILED",
                                "attempt": 0,
                                "message": f"recovery manager error: {exc}",
                            }
                        )
        except Exception as exc:
            monitoring_errors.append(f"service checker failed: {exc}")

        try:
            logs = self.log_parser.parse()
            monitoring_errors.extend(logs.errors)
        except Exception as exc:
            monitoring_errors.append(f"log parser failed: {exc}")

        status = self._status(system, services, logs, monitoring_errors)
        report: dict[str, Any] = {
            "status": status,
            "timestamp": timestamp,
            "system": system.to_dict() if system else None,
            "services": [service.to_dict() for service in services],
            "logs": logs.to_dict() if logs else None,
            "monitoring_errors": monitoring_errors,
            "recoveries": recovery_results,
        }
        return report

    def _status(
        self,
        system: SystemMetrics | None,
        services: list[ServiceHealth],
        logs: LogSummary | None,
        monitoring_errors: list[str],
    ) -> str:
        if system is None or system.errors or any(
            error.startswith("service checker failed") for error in monitoring_errors
        ):
            return "UNHEALTHY"
        if any(service.required and service.status == "DOWN" for service in services):
            return "UNHEALTHY"
        blocking_errors = [
            error
            for error in monitoring_errors
            if not (logs and logs.missing and error in logs.errors)
        ]
        if blocking_errors or any(service.status == "DOWN" for service in services):
            return "DEGRADED"
        if logs is None:
            return "DEGRADED"
        if (
            logs.error_count > self.thresholds.max_error_logs
            or logs.critical_count > self.thresholds.max_critical_logs
        ):
            return "DEGRADED"
        return "HEALTHY"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()