"""Standard-library HTTP health checks and YAML service configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import socket

import yaml


DEFAULT_SUCCESS_CODES = tuple(range(200, 300))


@dataclass(frozen=True)
class RecoveryPolicy:
    """Explicit, bounded recovery policy for one monitored service."""

    enabled: bool = False
    action: str = "none"
    max_attempts: int = 1
    cooldown_seconds: float = 300.0
    timeout_seconds: float = 5.0
    target_container: str | None = None


@dataclass(frozen=True)
class ServiceConfig:
    """Configuration for one HTTP service check."""

    name: str
    url: str
    required: bool = True
    timeout_seconds: float = 5.0
    expected_status_codes: tuple[int, ...] = DEFAULT_SUCCESS_CODES
    recovery: RecoveryPolicy = RecoveryPolicy()


@dataclass(frozen=True)
class ServiceHealth:
    """Result of one HTTP service check."""

    name: str
    url: str
    status: str
    status_code: int | None
    response_time_ms: float | None
    timestamp: str
    error: str | None = None
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this result."""
        result = asdict(self)
        result["url"] = _safe_url(self.url)
        return result


class ServiceConfigurationError(ValueError):
    """Raised when the service configuration cannot be used."""


def load_service_configs(config_path: str | Path) -> list[ServiceConfig]:
    """Load service definitions from a YAML file."""
    path = Path(config_path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ServiceConfigurationError(f"unable to read {path}: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("services"), list):
        raise ServiceConfigurationError("configuration must contain a services list")

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ServiceConfigurationError("defaults must be a mapping")
    default_timeout = float(defaults.get("timeout_seconds", 5.0))
    default_codes = _parse_status_codes(defaults.get("expected_status_codes"))

    configs: list[ServiceConfig] = []
    for index, item in enumerate(raw["services"]):
        if not isinstance(item, dict) or not item.get("name") or not item.get("url"):
            raise ServiceConfigurationError(
                f"service entry {index} must contain name and url"
            )
        try:
            timeout = float(item.get("timeout_seconds", default_timeout))
            if timeout <= 0:
                raise ValueError("timeout_seconds must be positive")
            codes = _parse_status_codes(
                item.get("expected_status_codes"), default=default_codes
            )
            recovery = _parse_recovery_policy(item.get("recovery"))
        except (TypeError, ValueError) as exc:
            raise ServiceConfigurationError(
                f"invalid configuration for service {item.get('name')}: {exc}"
            ) from exc
        configs.append(
            ServiceConfig(
                name=str(item["name"]),
                url=str(item["url"]),
                required=bool(item.get("required", True)),
                timeout_seconds=timeout,
                expected_status_codes=codes,
                recovery=recovery,
            )
        )
    return configs


def _parse_recovery_policy(value: Any) -> RecoveryPolicy:
    if value is None:
        return RecoveryPolicy()
    if not isinstance(value, dict):
        raise ValueError("recovery must be a mapping")
    enabled = bool(value.get("enabled", False))
    action = str(value.get("action", "none"))
    max_attempts = int(value.get("max_attempts", 1))
    cooldown = float(value.get("cooldown_seconds", 300.0))
    timeout = float(value.get("timeout_seconds", 5.0))
    target_container = value.get("target_container")
    if max_attempts < 1 or cooldown < 0 or timeout <= 0:
        raise ValueError(
            "recovery max_attempts must be positive, cooldown non-negative, "
            "and timeout positive"
        )
    if enabled and action == "none":
        raise ValueError("enabled recovery requires an explicit action")
    if target_container is not None and not isinstance(target_container, str):
        raise ValueError("recovery target_container must be a string")
    if enabled and action == "docker_restart" and not target_container:
        raise ValueError("docker_restart requires target_container")
    return RecoveryPolicy(enabled, action, max_attempts, cooldown, timeout, target_container)


def _parse_status_codes(
    value: Any,
    default: tuple[int, ...] = DEFAULT_SUCCESS_CODES,
) -> tuple[int, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not value:
        raise ValueError("expected_status_codes must be a non-empty list")
    codes = tuple(int(code) for code in value)
    if any(code < 100 or code > 599 for code in codes):
        raise ValueError("status codes must be between 100 and 599")
    return codes


class ServiceChecker:
    """Check multiple configured HTTP or HTTPS services independently."""

    def __init__(self, services: list[ServiceConfig]) -> None:
        self.services = tuple(services)

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "ServiceChecker":
        """Build a checker from a YAML configuration file."""
        return cls(load_service_configs(config_path))

    def check_all(self) -> list[ServiceHealth]:
        """Check every service; one failed check never stops the others."""
        results: list[ServiceHealth] = []
        for service in self.services:
            try:
                results.append(self.check_service(service))
            except Exception as exc:
                results.append(
                    ServiceHealth(
                        name=service.name,
                        url=service.url,
                        status="DOWN",
                        status_code=None,
                        response_time_ms=None,
                        timestamp=_utc_now(),
                        error=f"internal service check error: {exc}",
                        required=service.required,
                    )
                )
        return results

    def check_service(self, service: ServiceConfig) -> ServiceHealth:
        """Perform one bounded HTTP request and convert failures to DOWN."""
        timestamp = _utc_now()
        parsed = urlparse(service.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ServiceHealth(
                name=service.name,
                url=service.url,
                status="DOWN",
                status_code=None,
                response_time_ms=None,
                timestamp=timestamp,
                error="invalid URL; expected an http or https URL",
                required=service.required,
            )

        started = perf_counter()
        request = Request(service.url, headers={"User-Agent": "InfraWatch/0.1"})
        try:
            with urlopen(request, timeout=service.timeout_seconds) as response:
                status_code = int(response.getcode())
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            healthy = status_code in service.expected_status_codes
            return ServiceHealth(
                name=service.name,
                url=service.url,
                status="UP" if healthy else "DOWN",
                status_code=status_code,
                response_time_ms=elapsed_ms,
                timestamp=timestamp,
                error=None if healthy else f"unexpected HTTP status {status_code}",
                required=service.required,
            )
        except HTTPError as exc:
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            return ServiceHealth(
                name=service.name,
                url=service.url,
                status="DOWN",
                status_code=exc.code,
                response_time_ms=elapsed_ms,
                timestamp=timestamp,
                error=f"unexpected HTTP status {exc.code}",
                required=service.required,
            )
        except (TimeoutError, socket.timeout):
            return self._failed_result(service, timestamp, started, "request timed out")
        except URLError as exc:
            return self._failed_result(service, timestamp, started, f"connection failed: {exc.reason}")
        except (OSError, ValueError) as exc:
            return self._failed_result(service, timestamp, started, str(exc))

    @staticmethod
    def _failed_result(
        service: ServiceConfig,
        timestamp: str,
        started: float,
        error: str,
    ) -> ServiceHealth:
        return ServiceHealth(
            name=service.name,
            url=service.url,
            status="DOWN",
            status_code=None,
            response_time_ms=round((perf_counter() - started) * 1000, 2),
            timestamp=timestamp,
            error=error,
            required=service.required,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(url: str) -> str:
    """Keep service location context without exposing URL credentials or tokens."""
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        hostname = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))