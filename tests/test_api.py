from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.log_parser.log_parser import LogParser


HEALTHY_REPORT = {
    "status": "HEALTHY",
    "timestamp": "2026-10-09T00:00:00+00:00",
    "system": {
        "cpu_percent": 12.5,
        "memory_percent": 40.0,
        "disk_percent": 30.0,
        "uptime_seconds": 100.0,
    },
    "services": [
        {
            "name": "local-service",
            "url": "http://localhost:8000/",
            "status": "UP",
            "status_code": 200,
            "response_time_ms": 4.2,
            "timestamp": "2026-10-09T00:00:00+00:00",
            "error": None,
            "required": True,
        }
    ],
    "logs": {
        "severity_counts": {
            "DEBUG": 0,
            "INFO": 2,
            "WARNING": 0,
            "ERROR": 1,
            "CRITICAL": 0,
        },
        "error_count": 1,
        "critical_count": 0,
        "recent_errors": ["ERROR test entry"],
        "errors": [],
    },
    "monitoring_errors": [],
}


class FakeMonitor:
    def __init__(self, report: dict) -> None:
        self.report = report

    def collect(self) -> dict:
        return self.report


def test_health_returns_200_without_running_monitoring(monkeypatch) -> None:
    class FailingMonitor:
        def collect(self) -> dict:
            raise AssertionError("/health must not collect monitoring data")

    monkeypatch.setattr(app.state, "health_monitor", FailingMonitor())
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_returns_healthy_report(monkeypatch) -> None:
    monkeypatch.setattr(app.state, "health_monitor", FakeMonitor(HEALTHY_REPORT))
    response = TestClient(app).get("/status")
    assert response.status_code == 200
    assert response.json()["status"] == "HEALTHY"


def test_status_returns_503_for_unhealthy_report(monkeypatch) -> None:
    report = {**HEALTHY_REPORT, "status": "UNHEALTHY"}
    monkeypatch.setattr(app.state, "health_monitor", FakeMonitor(report))
    response = TestClient(app).get("/status")
    assert response.status_code == 503
    assert response.json()["status"] == "UNHEALTHY"


def test_logs_returns_bounded_recent_entries(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "application.log"
    log_path.write_text(
        "ERROR first\nCRITICAL second\nERROR third\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        app.state,
        "log_parser",
        LogParser(log_path, recent_limit=20),
    )
    response = TestClient(app).get("/logs?limit=1")
    assert response.status_code == 200
    assert response.json()["error_count"] == 2
    assert len(response.json()["recent_errors"]) == 1


def test_logs_handles_missing_file_safely(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        app.state,
        "log_parser",
        LogParser(tmp_path / "missing.log"),
    )
    response = TestClient(app).get("/logs")
    assert response.status_code == 503
    assert response.json() == {"detail": "Configured log file could not be read."}


def test_metrics_returns_prometheus_output(monkeypatch) -> None:
    monkeypatch.setattr(app.state, "health_monitor", FakeMonitor(HEALTHY_REPORT))
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "infrawatch_cpu_utilization_percent" in response.text
    assert "infrawatch_service_availability" in response.text
    assert 'required="true"' in response.text
    assert "infrawatch_log_severity_count" in response.text
    assert response.headers["content-type"].startswith("text/plain")


def test_repeated_metrics_requests_do_not_duplicate_registration(monkeypatch) -> None:
    monkeypatch.setattr(app.state, "health_monitor", FakeMonitor(HEALTHY_REPORT))
    client = TestClient(app)
    first = client.get("/metrics")
    second = client.get("/metrics")
    assert first.status_code == 200
    assert second.status_code == 200