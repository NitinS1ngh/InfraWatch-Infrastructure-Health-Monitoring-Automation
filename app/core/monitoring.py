"""Build shared monitoring components from local environment configuration."""

from __future__ import annotations

import os
import logging
from pathlib import Path

from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor
from app.monitoring.service_checker import ServiceChecker, ServiceConfigurationError
from app.monitoring.system_metrics import SystemMetricsCollector
from app.monitoring.recovery import RecoveryManager
from app.monitoring.docker_recovery import DockerContainerRestartHandler, DockerWorkerRecoveryHandler


logger = logging.getLogger(__name__)


class UnavailableServiceChecker:
    """Represent a configuration failure without falsely reporting no services."""

    def check_all(self) -> list[object]:
        raise RuntimeError("service configuration unavailable")


def build_health_monitor(project_root: Path | None = None) -> HealthMonitor:
    """Construct one monitor using paths configured by safe environment values."""
    root = project_root or Path(__file__).resolve().parents[2]
    services_path = _configured_path(
        "INFRAWATCH_SERVICES_CONFIG", root / "config" / "services.yaml", root
    )
    log_path = _configured_path(
        "INFRAWATCH_LOG_PATH", root / "logs" / "app.log", root
    )
    disk_path = os.getenv("INFRAWATCH_DISK_PATH", "/")
    cpu_interval = _configured_float("INFRAWATCH_CPU_INTERVAL", 0.1)

    try:
        service_checker = ServiceChecker.from_yaml(services_path)
    except ServiceConfigurationError:
        service_checker = UnavailableServiceChecker()

    dry_run = _configured_bool("INFRAWATCH_RECOVERY_DRY_RUN", True)
    docker_enabled = _configured_bool("INFRAWATCH_DOCKER_RECOVERY_ENABLED", False)
    allowed_containers = {
        name.strip()
        for name in os.getenv("INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS", "").split(",")
        if name.strip()
    }
    service_handlers = {}
    if docker_enabled and not dry_run:
        for service in (service_checker.services if isinstance(service_checker, ServiceChecker) else ()):
            policy = service.recovery
            if policy.enabled and policy.action == "docker_restart" and policy.target_container:
                try:
                    handler = DockerContainerRestartHandler(
                        policy.target_container,
                        allowed_containers,
                        timeout_seconds=policy.timeout_seconds,
                    )
                except ValueError as exc:
                    logger.error("recovery handler not enabled for %s: %s", service.name, exc)
                else:
                    service_handlers[(service.name, policy.action)] = handler
    worker_url = os.getenv("INFRAWATCH_RECOVERY_WORKER_URL")
    worker_token = os.getenv("INFRAWATCH_RECOVERY_WORKER_TOKEN")
    if worker_url and worker_token and not dry_run:
        service_handlers = {}
        for service in (service_checker.services if isinstance(service_checker, ServiceChecker) else ()):
            policy = service.recovery
            if policy.enabled and policy.action == "docker_restart" and policy.target_container:
                try:
                    service_handlers[(service.name, policy.action)] = DockerWorkerRecoveryHandler(
                        worker_url, worker_token, policy.target_container, policy.timeout_seconds
                    )
                except ValueError as exc:
                    logger.error("recovery worker not enabled for %s: %s", service.name, exc)

    return HealthMonitor(
        system_collector=SystemMetricsCollector(
            disk_path=disk_path,
            cpu_interval=cpu_interval,
        ),
        service_checker=service_checker,
        log_parser=LogParser(log_path=log_path),
        recovery_manager=RecoveryManager(
            dry_run=dry_run,
            service_handlers=service_handlers,
        ),
    )


def _configured_path(name: str, default: Path, root: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _configured_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


def _configured_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}