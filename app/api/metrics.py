"""Reusable Prometheus metrics for coordinator health reports."""

from __future__ import annotations

from typing import Any

from prometheus_client import CollectorRegistry, Gauge, generate_latest


class PrometheusMetrics:
    """Own one registry and update it from serialized health reports."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.cpu_percent = Gauge(
            "infrawatch_cpu_utilization_percent",
            "Current system CPU utilization percentage.",
            registry=self.registry,
        )
        self.memory_percent = Gauge(
            "infrawatch_memory_utilization_percent",
            "Current system memory utilization percentage.",
            registry=self.registry,
        )
        self.disk_percent = Gauge(
            "infrawatch_disk_utilization_percent",
            "Current disk utilization percentage.",
            registry=self.registry,
        )
        self.uptime_seconds = Gauge(
            "infrawatch_system_uptime_seconds",
            "Current system uptime in seconds.",
            registry=self.registry,
        )
        self.service_availability = Gauge(
            "infrawatch_service_availability",
            "Whether a monitored service is currently available (1 or 0).",
            ["service", "required"],
            registry=self.registry,
        )
        self.service_response_time = Gauge(
            "infrawatch_service_response_time_milliseconds",
            "Latest monitored service response time in milliseconds.",
            ["service"],
            registry=self.registry,
        )
        self.log_severity_count = Gauge(
            "infrawatch_log_severity_count",
            "Number of parsed log entries by severity in the configured window.",
            ["severity"],
            registry=self.registry,
        )

    def render(self, report: dict[str, Any]) -> bytes:
        """Update stable metric objects and render one report."""
        system = report.get("system") or {}
        self._set_or_nan(self.cpu_percent, system.get("cpu_percent"))
        self._set_or_nan(self.memory_percent, system.get("memory_percent"))
        self._set_or_nan(self.disk_percent, system.get("disk_percent"))
        self._set_or_nan(self.uptime_seconds, system.get("uptime_seconds"))

        self.service_availability.clear()
        self.service_response_time.clear()
        for service in report.get("services") or []:
            name = service.get("name")
            if not name:
                continue
            self.service_availability.labels(
                service=name,
                required=str(bool(service.get("required", True))).lower(),
            ).set(
                1.0 if service.get("status") == "UP" else 0.0
            )
            response_time = service.get("response_time_ms")
            if response_time is not None:
                self.service_response_time.labels(service=name).set(response_time)

        logs = report.get("logs") or {}
        severity_counts = logs.get("severity_counts") or {}
        self.log_severity_count.clear()
        for severity in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            self.log_severity_count.labels(severity=severity.lower()).set(
                severity_counts.get(severity, 0)
            )

        return generate_latest(self.registry)

    @staticmethod
    def _set_or_nan(metric: Gauge, value: Any) -> None:
        metric.set(value if value is not None else float("nan"))