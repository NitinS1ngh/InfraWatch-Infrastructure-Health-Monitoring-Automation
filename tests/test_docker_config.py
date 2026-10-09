from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).parents[1]


def test_dockerfile_has_expected_runtime_command() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in dockerfile
    assert "COPY requirements.txt ." in dockerfile
    assert '"app.main:app"' in dockerfile
    assert '"--host", "0.0.0.0", "--port", "8000"' in dockerfile
    assert "PYTHONUNBUFFERED=1" in dockerfile
    assert "USER infrawatch" in dockerfile


def test_dockerignore_excludes_local_artifacts() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in (".venv/", ".git/", ".env", "__pycache__/", ".pytest_cache/"):
        assert entry in dockerignore
    assert "tests/" in dockerignore
    assert "config/*" in dockerignore
    assert "!config/services.yaml" in dockerignore


def load_compose() -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )


def test_compose_api_build_and_loopback_port() -> None:
    api = load_compose()["services"]["api"]
    assert api["build"] == {"context": ".", "dockerfile": "Dockerfile"}
    assert api["ports"] == [
        "${INFRAWATCH_BIND_ADDRESS:-127.0.0.1}:${INFRAWATCH_API_PORT:-8000}:8000"
    ]


def test_compose_healthcheck_targets_health_endpoint() -> None:
    healthcheck = load_compose()["services"]["api"]["healthcheck"]
    assert healthcheck["test"][0:3] == ["CMD", "python", "-c"]
    assert "/health" in healthcheck["test"][3]


def test_compose_mounts_config_read_only_and_logs() -> None:
    api = load_compose()["services"]["api"]
    assert "./config/services.yaml:/app/config/services.yaml:ro" in api["volumes"]
    assert "./logs:/app/logs" in api["volumes"]


def test_compose_paths_and_environment_match_application() -> None:
    api = load_compose()["services"]["api"]
    environment = api["environment"]
    assert environment == {
        "INFRAWATCH_SERVICES_CONFIG": "/app/config/services.yaml",
        "INFRAWATCH_LOG_PATH": "/app/logs/app.log",
        "INFRAWATCH_DISK_PATH": "/",
        "INFRAWATCH_CPU_INTERVAL": "0.1",
        "INFRAWATCH_RECOVERY_DRY_RUN": "${INFRAWATCH_RECOVERY_DRY_RUN:-true}",
        "INFRAWATCH_DOCKER_RECOVERY_ENABLED": "${INFRAWATCH_DOCKER_RECOVERY_ENABLED:-false}",
        "INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS": "${INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS:-}",
        "INFRAWATCH_RECOVERY_WORKER_URL": "${INFRAWATCH_RECOVERY_WORKER_URL:-http://recovery-worker:8090}",
        "INFRAWATCH_RECOVERY_WORKER_TOKEN": "${INFRAWATCH_RECOVERY_WORKER_TOKEN:-}",
    }


def test_compose_has_no_privileged_or_docker_socket_access() -> None:
    api = load_compose()["services"]["api"]
    assert api.get("privileged") is not True
    assert not any("docker.sock" in volume for volume in api.get("volumes", []))