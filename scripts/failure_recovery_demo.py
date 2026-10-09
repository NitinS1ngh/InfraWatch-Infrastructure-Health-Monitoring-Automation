"""Exercise a loopback-only HTTP service through failure and recovery states."""

from __future__ import annotations

from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
from typing import Any

from app.monitoring.service_checker import ServiceChecker, ServiceConfig


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        service: "LocalTestService" = self.server.service  # type: ignore[attr-defined]
        with service._lock:
            healthy = service.healthy
        self.send_response(200 if healthy else 503)
        self.end_headers()
        self.wfile.write(b"healthy\n" if healthy else b"unhealthy\n")

    def log_message(self, format: str, *args: Any) -> None:
        return None


class LocalTestService(AbstractContextManager["LocalTestService"]):
    """A disposable loopback HTTP service with a controllable health response."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._ready = Event()
        self.healthy = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        self.server.service = self  # type: ignore[attr-defined]
        self.thread = Thread(target=self._serve, name="infrawatch-test-service", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/health"

    def start(self) -> "LocalTestService":
        self.thread.start()
        self._ready.wait(timeout=2)
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def set_healthy(self, healthy: bool) -> None:
        with self._lock:
            self.healthy = healthy

    def _serve(self) -> None:
        self._ready.set()
        self.server.serve_forever(poll_interval=0.05)

    def __enter__(self) -> "LocalTestService":
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.stop()


def run_demo() -> list[dict[str, str]]:
    """Return UP, DOWN, and recovered UP results from one isolated service."""
    with LocalTestService() as service:
        checker = ServiceChecker(
            [ServiceConfig(name="local-test-service", url=service.url, timeout_seconds=1)]
        )
        results = [checker.check_all()[0].status]
        service.set_healthy(False)
        results.append(checker.check_all()[0].status)
        service.set_healthy(True)
        results.append(checker.check_all()[0].status)
    return [{"step": step, "status": status} for step, status in zip(("healthy", "failed", "recovered"), results)]


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2))