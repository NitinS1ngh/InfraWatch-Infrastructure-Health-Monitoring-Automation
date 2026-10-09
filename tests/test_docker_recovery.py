from __future__ import annotations

import time
from pathlib import Path
from urllib.request import urlopen

import pytest

from app.monitoring.docker_recovery import DockerContainerRestartHandler


def test_docker_handler_rejects_unauthorized_container() -> None:
    with pytest.raises(ValueError):
        DockerContainerRestartHandler("not-allowed", {"allowed"})


def test_docker_handler_uses_only_allowlisted_client() -> None:
    class FakeContainer:
        attrs = {"State": {"Running": True}}

        def restart(self, timeout: int) -> None:
            assert timeout == 5

        def reload(self) -> None:
            return None

    class FakeContainers:
        def get(self, name: str) -> FakeContainer:
            assert name == "allowed"
            return FakeContainer()

    class FakeClient:
        containers = FakeContainers()

    handler = DockerContainerRestartHandler(
        "allowed", {"allowed"}, timeout_seconds=5, client=FakeClient()
    )
    assert handler() is True


def test_real_disposable_container_restarts_and_restores_health() -> None:
    docker = pytest.importorskip("docker")
    try:
        socket_path = Path.home() / ".docker" / "run" / "docker.sock"
        client = docker.DockerClient(base_url=f"unix://{socket_path}")
        client.version()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker runtime unavailable for disposable recovery test: {exc}")
    name = "infrawatch-recovery-disposable"
    container = None
    try:
        try:
            client.containers.get(name).remove(force=True)
        except docker.errors.NotFound:
            pass
        container = client.containers.run(
            "infrawatch-api",
            ["python", "-m", "http.server", "18080", "--bind", "0.0.0.0"],
            name=name,
            detach=True,
            ports={"18080/tcp": ("127.0.0.1", 18081)},
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if urlopen("http://127.0.0.1:18081", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("disposable service did not become healthy")

        container.stop()
        handler = DockerContainerRestartHandler(name, {name}, timeout_seconds=5, client=client)
        assert handler() is True
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if urlopen("http://127.0.0.1:18081", timeout=1).status == 200:
                    return
            except OSError:
                time.sleep(0.2)
        raise AssertionError("disposable service did not recover after restart")
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker runtime unavailable for disposable recovery test: {exc}")
    finally:
        if container is not None:
            container.remove(force=True)