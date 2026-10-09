from app.monitoring.service_checker import ServiceChecker, ServiceConfig
from scripts.failure_recovery_demo import LocalTestService


def test_local_service_failure_and_recovery_sequence() -> None:
    with LocalTestService() as service:
        checker = ServiceChecker(
            [ServiceConfig(name="local-test-service", url=service.url, timeout_seconds=1)]
        )

        assert checker.check_all()[0].status == "UP"
        service.set_healthy(False)
        failed = checker.check_all()[0]
        assert failed.status == "DOWN"
        assert failed.status_code == 503

        service.set_healthy(True)
        recovered = checker.check_all()[0]
        assert recovered.status == "UP"
        assert recovered.status_code == 200