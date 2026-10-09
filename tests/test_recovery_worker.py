from __future__ import annotations

import os
from pathlib import Path
import json
from http.client import HTTPConnection
import threading
import threading
import time
from urllib.request import urlopen

import pytest

from app.monitoring.docker_recovery import DockerWorkerRecoveryHandler
from app.recovery_worker import RecoveryRequestHandler, RecoveryWorker


def test_worker_requires_token_and_allowlisted_target() -> None:
    assert "X-InfraWatch-Token" in Path("app/recovery_worker.py").read_text()
    assert "allowed_containers" in Path("app/recovery_worker.py").read_text()


def test_worker_rejects_invalid_token_action_and_fields(monkeypatch) -> None:
    from http.server import ThreadingHTTPServer

    os.environ["INFRAWATCH_RECOVERY_WORKER_TOKEN"] = "test-worker-token-1234567890"
    os.environ["INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS"] = "allowed"
    worker = RecoveryWorker()
    server = ThreadingHTTPServer(("127.0.0.1", 18085), RecoveryRequestHandler)
    server.worker = worker  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def post(token: str, payload: dict) -> int:
            connection = HTTPConnection("127.0.0.1", 18085, timeout=2)
            connection.request(
                "POST", "/recover", json.dumps(payload),
                {"Content-Type": "application/json", "X-InfraWatch-Token": token},
            )
            response = connection.getresponse()
            response.read()
            connection.close()
            return response.status

        assert post("wrong-token-1234567890", {"action": "docker_restart", "container_name": "allowed"}) == 403
        assert post(worker.token, {"action": "shell", "container_name": "allowed"}) == 403
        assert post(worker.token, {"action": "docker_restart", "container_name": "allowed", "extra": "rejected"}) == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_worker_restarts_disposable_container_without_api_socket_mount() -> None:
    docker = pytest.importorskip("docker")
    socket_path = Path.home() / ".docker" / "run" / "docker.sock"
    try:
        client = docker.DockerClient(base_url=f"unix://{socket_path}")
        client.version()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker runtime unavailable: {exc}")

    from http.server import ThreadingHTTPServer

    name = "infrawatch-worker-disposable"
    container = None
    token = "test-worker-token-1234567890"
    try:
        try:
            client.containers.get(name).remove(force=True)
        except docker.errors.NotFound:
            pass
        container = client.containers.run(
            "infrawatch-api",
            ["python", "-m", "http.server", "18082", "--bind", "0.0.0.0"],
            name=name,
            detach=True,
            ports={"18082/tcp": ("127.0.0.1", 18083)},
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if urlopen("http://127.0.0.1:18083", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("worker disposable service did not become healthy")

        os.environ["INFRAWATCH_RECOVERY_WORKER_TOKEN"] = token
        os.environ["INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS"] = name
        os.environ["DOCKER_HOST"] = f"unix://{socket_path}"
        worker = RecoveryWorker()
        server = ThreadingHTTPServer(("127.0.0.1", 18084), RecoveryRequestHandler)
        server.worker = worker  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        container.stop()
        assert DockerWorkerRecoveryHandler(
            "http://127.0.0.1:18084", token, name, 5
        )() is True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if urlopen("http://127.0.0.1:18083", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("worker did not restore disposable service")
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    finally:
        if container is not None:
            container.remove(force=True)