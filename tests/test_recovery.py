from __future__ import annotations

from pathlib import Path

from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor
from app.monitoring.recovery import RecoveryManager
from app.monitoring.service_checker import ServiceChecker, ServiceConfig, ServiceHealth
from app.monitoring.system_metrics import SystemMetrics
from scripts.failure_recovery_demo import LocalTestService


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def service_config(**overrides: object) -> ServiceConfig:
    recovery = {
        "enabled": True,
        "action": "restart-test-service",
        "max_attempts": 2,
        "cooldown_seconds": 30.0,
        "timeout_seconds": 0.1,
    }
    recovery.update(overrides)
    from app.monitoring.service_checker import RecoveryPolicy

    return ServiceConfig(
        name="test-service",
        url="http://127.0.0.1:1/",
        recovery=RecoveryPolicy(**recovery),
    )


def down_health() -> ServiceHealth:
    return ServiceHealth(
        name="test-service",
        url="http://127.0.0.1:1/",
        status="DOWN",
        status_code=None,
        response_time_ms=None,
        timestamp="2026-10-09T00:00:00+00:00",
    )


def test_successful_recovery_is_opt_in_and_logged() -> None:
    calls: list[str] = []
    manager = RecoveryManager(
        handlers={"restart-test-service": lambda: calls.append("called") or True},
        dry_run=False,
    )
    result = manager.recover(service_config(), down_health())
    assert result.status == "SUCCEEDED"
    assert result.attempt == 1
    assert calls == ["called"]


def test_failed_recovery_is_reported_without_raising() -> None:
    manager = RecoveryManager(
        handlers={"restart-test-service": lambda: (_ for _ in ()).throw(RuntimeError("boom"))},
        dry_run=False,
    )
    result = manager.recover(service_config(), down_health())
    assert result.status == "FAILED"
    assert "boom" in result.message


def test_retry_limit_and_cooldown_are_bounded() -> None:
    clock = FakeClock()
    calls: list[str] = []
    manager = RecoveryManager(
        handlers={"restart-test-service": lambda: calls.append("called") or False},
        dry_run=False,
        clock=clock,
    )
    config = service_config(max_attempts=2, cooldown_seconds=30.0)
    assert manager.recover(config, down_health()).status == "FAILED"
    assert manager.recover(config, down_health()).status == "COOLDOWN"
    clock.value += 31
    assert manager.recover(config, down_health()).status == "FAILED"
    clock.value += 31
    assert manager.recover(config, down_health()).status == "RETRY_LIMIT"
    assert calls == ["called", "called"]


def test_disabled_recovery_and_dry_run_do_not_execute_handlers() -> None:
    calls: list[str] = []
    handler = lambda: calls.append("called") or True
    disabled = service_config(enabled=False)
    assert RecoveryManager({"restart-test-service": handler}, dry_run=False).recover(
        disabled, down_health()
    ).status == "DISABLED"
    dry_run = RecoveryManager({"restart-test-service": handler}, dry_run=True).recover(
        service_config(), down_health()
    )
    assert dry_run.status == "DRY_RUN"
    assert calls == []


def test_recovery_does_not_run_for_healthy_service() -> None:
    calls: list[str] = []
    manager = RecoveryManager({"restart-test-service": lambda: calls.append("called") or True}, dry_run=False)
    healthy = ServiceHealth(**{**down_health().__dict__, "status": "UP", "status_code": 200})
    assert manager.recover(service_config(), healthy).status == "SKIPPED"
    assert calls == []


def test_disposable_local_service_recovers_through_coordinator(tmp_path: Path) -> None:
    with LocalTestService() as local_service:
        local_service.set_healthy(False)
        config = ServiceConfig(
            name="disposable",
            url=local_service.url,
            recovery=service_config().recovery,
        )
        checker = ServiceChecker([config])
        manager = RecoveryManager(
            handlers={"restart-test-service": lambda: local_service.set_healthy(True) or True},
            dry_run=False,
        )
        system = SystemMetrics(
            timestamp="2026-10-09T00:00:00+00:00",
            cpu_percent=1.0,
            memory_percent=1.0,
            memory_total_bytes=1,
            memory_used_bytes=1,
            memory_available_bytes=0,
            disk_percent=1.0,
            disk_total_bytes=1,
            disk_used_bytes=1,
            disk_free_bytes=0,
            uptime_seconds=1.0,
        )
        collector = type("Collector", (), {"collect": lambda self: system})()
        log_path = tmp_path / "app.log"
        log_path.touch()
        report = HealthMonitor(collector, checker, LogParser(log_path), recovery_manager=manager).collect()
        assert report["services"][0]["status"] == "DOWN"
        assert report["recoveries"][0]["status"] == "SUCCEEDED"
        assert checker.check_all()[0].status == "UP"


def test_recovery_manager_failure_does_not_break_monitoring(tmp_path: Path) -> None:
    config = service_config()
    checker = ServiceChecker([config])
    manager = RecoveryManager(dry_run=False)
    manager.recover = lambda *_args: (_ for _ in ()).throw(RuntimeError("manager unavailable"))
    system = SystemMetrics(
        timestamp="2026-10-09T00:00:00+00:00",
        cpu_percent=1.0,
        memory_percent=1.0,
        memory_total_bytes=1,
        memory_used_bytes=1,
        memory_available_bytes=0,
        disk_percent=1.0,
        disk_total_bytes=1,
        disk_used_bytes=1,
        disk_free_bytes=0,
        uptime_seconds=1.0,
    )
    collector = type("Collector", (), {"collect": lambda self: system})()
    log_path = tmp_path / "app.log"
    log_path.touch()
    report = HealthMonitor(
        collector,
        checker,
        LogParser(log_path),
        recovery_manager=manager,
    ).collect()
    assert report["status"] == "UNHEALTHY"
    assert report["recoveries"][0]["status"] == "FAILED"
    assert "manager unavailable" in report["recoveries"][0]["message"]