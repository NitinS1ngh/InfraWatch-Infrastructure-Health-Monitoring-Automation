from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from app.monitoring.service_checker import ServiceChecker, ServiceConfig


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status


def make_service() -> ServiceConfig:
    return ServiceConfig(name="local", url="http://localhost:8000/")


def test_http_2xx_health_check() -> None:
    with patch("app.monitoring.service_checker.urlopen", return_value=FakeResponse(204)):
        result = ServiceChecker([make_service()]).check_all()[0]
    assert result.status == "UP"
    assert result.status_code == 204
    assert result.error is None


def test_http_5xx_health_check() -> None:
    with patch("app.monitoring.service_checker.urlopen", return_value=FakeResponse(503)):
        result = ServiceChecker([make_service()]).check_all()[0]
    assert result.status == "DOWN"
    assert result.status_code == 503
    assert result.error == "unexpected HTTP status 503"


def test_connection_failure_and_timeout() -> None:
    with patch(
        "app.monitoring.service_checker.urlopen",
        side_effect=URLError("connection refused"),
    ):
        failed = ServiceChecker([make_service()]).check_all()[0]
    assert failed.status == "DOWN"
    assert "connection failed" in (failed.error or "")

    with patch("app.monitoring.service_checker.urlopen", side_effect=TimeoutError):
        timed_out = ServiceChecker([make_service()]).check_all()[0]
    assert timed_out.status == "DOWN"
    assert timed_out.error == "request timed out"


def test_recovery_policy_loads_explicit_opt_in_values(tmp_path) -> None:
    config_path = tmp_path / "services.yaml"
    config_path.write_text(
        """services:\n  - name: local\n    url: http://127.0.0.1:8000/\n    recovery:\n      enabled: true\n      action: restart-local\n      max_attempts: 2\n      cooldown_seconds: 10\n      timeout_seconds: 1\n""",
        encoding="utf-8",
    )
    service = ServiceChecker.from_yaml(config_path).services[0]
    assert service.recovery.enabled is True
    assert service.recovery.action == "restart-local"
    assert service.recovery.max_attempts == 2