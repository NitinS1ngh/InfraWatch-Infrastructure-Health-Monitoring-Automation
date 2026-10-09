"""Opt-in internal recovery worker with Docker access isolated from the API."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import hmac
from threading import Lock

from app.monitoring.docker_recovery import DockerContainerRestartHandler


class RecoveryRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        worker: "RecoveryWorker" = self.server.worker  # type: ignore[attr-defined]
        supplied_token = self.headers.get("X-InfraWatch-Token", "")
        if self.path != "/recover" or not hmac.compare_digest(supplied_token, worker.token):
            self._respond(403, {"status": "FAILED", "message": "request rejected"})
            return
        try:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None or int(raw_length) > 4096:
                raise ValueError("invalid request size")
            length = int(raw_length)
            payload = json.loads(self.rfile.read(length))
            if set(payload) != {"action", "container_name"}:
                raise ValueError("unexpected request fields")
            if payload.get("action") != "docker_restart":
                raise ValueError("unsupported recovery action")
            container_name = payload.get("container_name")
            if container_name not in worker.allowed_containers:
                raise ValueError("container is not allowlisted")
            if not worker._begin(container_name):
                raise ValueError("recovery already in progress")
            handler = DockerContainerRestartHandler(
                container_name, worker.allowed_containers, timeout_seconds=worker.timeout_seconds
            )
            try:
                handler()
            finally:
                worker._end(container_name)
            self._respond(200, {"status": "SUCCEEDED", "message": "container restarted"})
        except Exception as exc:
            status = 403 if isinstance(exc, ValueError) else 500
            message = str(exc) if isinstance(exc, ValueError) else "recovery failed"
            self._respond(status, {"status": "FAILED", "message": message})

    def _respond(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return None


class RecoveryWorker:
    def __init__(self) -> None:
        self.token = os.getenv("INFRAWATCH_RECOVERY_WORKER_TOKEN", "")
        if len(self.token) < 16 or self.token.startswith(("change-me", "replace-with")):
            raise ValueError("INFRAWATCH_RECOVERY_WORKER_TOKEN must be at least 16 characters")
        self.allowed_containers = {
            item.strip()
            for item in os.getenv("INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS", "").split(",")
            if item.strip()
        }
        self.timeout_seconds = float(os.getenv("INFRAWATCH_RECOVERY_WORKER_TIMEOUT", "10"))
        self._active: set[str] = set()
        self._active_lock = Lock()

    def _begin(self, container_name: str) -> bool:
        with self._active_lock:
            if container_name in self._active:
                return False
            self._active.add(container_name)
            return True

    def _end(self, container_name: str) -> None:
        with self._active_lock:
            self._active.discard(container_name)

    def serve(self) -> None:
        server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("INFRAWATCH_RECOVERY_WORKER_PORT", "8090"))), RecoveryRequestHandler)
        server.worker = self  # type: ignore[attr-defined]
        server.serve_forever()


if __name__ == "__main__":
    RecoveryWorker().serve()