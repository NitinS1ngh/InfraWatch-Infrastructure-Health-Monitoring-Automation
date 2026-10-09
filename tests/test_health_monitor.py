from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor
from app.monitoring.service_checker import ServiceChecker, ServiceHealth
from app.monitoring.system_metrics import SystemMetrics


@dataclass
class StubSystemCollector:
    result: SystemMetrics | None

    def collect(self) -> SystemMetrics:
        if self.result is None:
            raise RuntimeError("metrics unavailable")
        return self.result


class StubServiceChecker:
    def __init__(self, result: list[ServiceHealth]) -> None:
        self.result = result

    def check_all(self) -> list[ServiceHealth]:
        return self.result


def system_metrics() -> SystemMetrics:
    return SystemMetrics(
        timestamp="2026-10-09T10:00:00+00:00",
        cpu_percent=10.0,
        memory_percent=20.0,
        memory_total_bytes=100,
        memory_used_bytes=20,
        memory_available_bytes=80,
        disk_percent=30.0,
        disk_total_bytes=100,
        disk_used_bytes=30,
        disk_free_bytes=70,
        uptime_seconds=3600.0,
    )


def service(status: str, required: bool = True) -> ServiceHealth:
    return ServiceHealth(
        name="local",
        url="http://localhost:8000/",
        status=status,
        status_code=200 if status == "UP" else None,
        response_time_ms=1.0,
        timestamp="2026-10-09T10:00:00+00:00",
        required=required,
    )


def make_monitor(
    system: SystemMetrics | None,
    services: list[ServiceHealth],
    log_path: Path | None = None,
) -> HealthMonitor:
    return HealthMonitor(
        StubSystemCollector(system),
        StubServiceChecker(services),
        LogParser(log_path or Path(__file__).parent / "fixtures" / "sample_application.log"),
    )


def test_health_report_when_all_checks_pass(tmp_path: Path) -> None:
    clean_log = tmp_path / "clean.log"
    clean_log.touch()
    report = make_monitor(system_metrics(), [service("UP")], clean_log).collect()
    assert report["status"] == "HEALTHY"
    assert report["services"][0]["status"] == "UP"


def test_missing_optional_log_is_reported_without_degrading_service_status(
    tmp_path: Path,
) -> None:
    report = make_monitor(
        system_metrics(),
        [service("UP")],
        tmp_path / "missing.log",
    ).collect()
    assert report["status"] == "HEALTHY"
    assert report["logs"]["missing"] is True
    assert report["logs"]["errors"]


def test_health_report_when_required_service_is_down() -> None:
    report = make_monitor(system_metrics(), [service("DOWN")]).collect()
    assert report["status"] == "UNHEALTHY"


def test_health_report_when_monitoring_data_cannot_be_collected() -> None:
    report = make_monitor(None, [service("UP")]).collect()
    assert report["status"] == "UNHEALTHY"
    assert report["monitoring_errors"]