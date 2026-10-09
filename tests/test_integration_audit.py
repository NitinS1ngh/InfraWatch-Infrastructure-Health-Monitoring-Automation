from pathlib import Path
from unittest.mock import Mock

from app.api.metrics import PrometheusMetrics
from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor
from app.monitoring.system_metrics import SystemMetrics
from app.monitoring.service_checker import ServiceChecker, ServiceConfig
from app.monitoring.service_checker import ServiceHealth
from scripts.failure_recovery_demo import LocalTestService


PROJECT_ROOT = Path(__file__).parents[1]


def make_system_metrics() -> SystemMetrics:
    return SystemMetrics(
        timestamp="2026-10-09T00:00:00+00:00",
        cpu_percent=42.0,
        memory_percent=51.0,
        memory_total_bytes=100,
        memory_used_bytes=51,
        memory_available_bytes=49,
        disk_percent=33.0,
        disk_total_bytes=100,
        disk_used_bytes=33,
        disk_free_bytes=67,
        uptime_seconds=3600.0,
    )


def build_monitor(service_checker: ServiceChecker, tmp_path: Path) -> HealthMonitor:
    system_collector = Mock()
    system_collector.collect.return_value = make_system_metrics()
    log_path = tmp_path / "app.log"
    log_path.touch()
    return HealthMonitor(
        system_collector=system_collector,
        service_checker=service_checker,
        log_parser=LogParser(log_path),
    )


def test_required_service_failure_propagates_into_health_report(tmp_path: Path) -> None:
    with LocalTestService() as service:
        service.set_healthy(False)
        checker = ServiceChecker(
            [ServiceConfig(name="required-local", url=service.url, required=True)]
        )
        report = build_monitor(checker, tmp_path).collect()

    assert report["status"] == "UNHEALTHY"
    assert report["services"][0]["status"] == "DOWN"
    assert report["services"][0]["required"] is True


def test_prometheus_metrics_match_coordinator_report_and_clear_stale_values() -> None:
    exporter = PrometheusMetrics()
    report = {
        "system": {
            "cpu_percent": 42.0,
            "memory_percent": 51.0,
            "disk_percent": 33.0,
            "uptime_seconds": 3600.0,
        },
        "services": [
            {
                "name": "required-local",
                "required": True,
                "status": "UP",
                "response_time_ms": 12.5,
            }
        ],
        "logs": {"severity_counts": {"ERROR": 2, "CRITICAL": 1}},
    }
    healthy_metrics = exporter.render(report).decode()
    assert "infrawatch_cpu_utilization_percent 42.0" in healthy_metrics
    assert 'infrawatch_service_availability{required="true",service="required-local"} 1.0' in healthy_metrics
    assert 'infrawatch_log_severity_count{severity="error"} 2.0' in healthy_metrics

    unavailable_metrics = exporter.render({"system": {}, "services": [], "logs": {}}).decode()
    assert "infrawatch_cpu_utilization_percent NaN" in unavailable_metrics
    assert "infrawatch_cpu_utilization_percent 42.0" not in unavailable_metrics


def test_configuration_paths_and_metric_references_are_cross_component_consistent() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    prometheus = (PROJECT_ROOT / "config/prometheus/prometheus.yml").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "config/grafana/dashboards/infrawatch-overview.json").read_text(encoding="utf-8")
    ansible_defaults = (PROJECT_ROOT / "ansible/inventory/group_vars/all.yml").read_text(encoding="utf-8")

    assert "/app/config/services.yaml" in compose
    assert "/app/logs/app.log" in compose
    assert "api:8000" in prometheus
    assert "infrawatch_cpu_utilization_percent" in dashboard
    assert "infrawatch_service_availability" in dashboard
    assert "127.0.0.1:8000/health" in ansible_defaults
    assert "127.0.0.1:9090/-/ready" in ansible_defaults
    assert "127.0.0.1:3000/api/health" in ansible_defaults


def test_secret_and_host_mount_hygiene_is_preserved() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "*.pem" in gitignore and "*.key" in gitignore
    assert ".venv/" in dockerignore and ".git/" in dockerignore
    assert "*.pem" in dockerignore and "*.key" in dockerignore
    compose_data = __import__("yaml").safe_load(compose)
    assert not any("docker.sock" in volume for volume in compose_data["services"]["api"].get("volumes", []))
    assert "docker.sock" in compose_data["services"]["recovery-worker"]["volumes"][0]
    assert "privileged:" not in compose


def test_serialized_service_urls_do_not_expose_credentials_or_query_tokens() -> None:
    result = ServiceHealth(
        name="private-service",
        url="https://user:secret@example.test:8443/health?token=secret",
        status="UP",
        status_code=200,
        response_time_ms=1.0,
        timestamp="2026-10-09T00:00:00+00:00",
    ).to_dict()
    assert result["url"] == "https://example.test:8443/health"
    assert "secret" not in result["url"]