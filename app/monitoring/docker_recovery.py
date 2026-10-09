"""Restricted Docker container recovery through the Docker Engine API.

This module deliberately uses the Docker SDK rather than shelling out to the
Docker CLI. Access requires the caller to have Docker socket permissions, so it
is not enabled by the API defaults and must be injected explicitly by trusted
deployment code.
"""

from __future__ import annotations

from time import monotonic
from typing import Any
import json
from urllib.request import Request, urlopen
from urllib.error import URLError


class DockerRecoveryError(RuntimeError):
    """Raised when a permitted Docker recovery cannot be completed."""


class DockerContainerRestartHandler:
    """Restart exactly one configured container from an explicit allowlist."""

    def __init__(
        self,
        container_name: str,
        allowed_container_names: set[str],
        timeout_seconds: float = 10.0,
        client: Any | None = None,
    ) -> None:
        if not container_name or container_name not in allowed_container_names:
            raise ValueError("container_name must be an explicit allowed container")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.container_name = container_name
        self.allowed_container_names = frozenset(allowed_container_names)
        self.timeout_seconds = timeout_seconds
        self._client = client

    def __call__(self) -> bool:
        """Restart the allowlisted container and verify it is running."""
        client = self._client or self._load_client()
        started = monotonic()
        container = client.containers.get(self.container_name)
        if monotonic() - started > self.timeout_seconds:
            raise DockerRecoveryError("container lookup timed out")
        container.restart(timeout=max(1, int(self.timeout_seconds)))
        container.reload()
        if not container.attrs.get("State", {}).get("Running", False):
            raise DockerRecoveryError("container did not return to running state")
        return True

    @staticmethod
    def _load_client() -> Any:
        try:
            import docker
        except ImportError as exc:
            raise DockerRecoveryError(
                "Docker SDK is not installed; recovery handler is unavailable"
            ) from exc
        try:
            return docker.from_env()
        except Exception as exc:
            raise DockerRecoveryError(f"Docker API connection failed: {exc}") from exc


class DockerWorkerRecoveryHandler:
    """Request one fixed container restart from the internal recovery worker."""

    def __init__(self, worker_url: str, token: str, container_name: str, timeout_seconds: float = 10.0) -> None:
        if not worker_url.startswith("http://") or not token or not container_name:
            raise ValueError("worker URL, token, and container name are required")
        self.worker_url = worker_url.rstrip("/") + "/recover"
        self.token = token
        self.container_name = container_name
        self.timeout_seconds = timeout_seconds

    def __call__(self) -> bool:
        payload = json.dumps(
            {"action": "docker_restart", "container_name": self.container_name}
        ).encode("utf-8")
        request = Request(
            self.worker_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "X-InfraWatch-Token": self.token},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError) as exc:
            raise DockerRecoveryError(f"recovery worker request failed: {exc}") from exc
        if response.status != 200 or body.get("status") != "SUCCEEDED":
            raise DockerRecoveryError(body.get("message", "recovery worker rejected request"))
        return True